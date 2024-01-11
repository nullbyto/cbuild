#!/usr/bin/env python3

import subprocess
import platform
import os
import re
import argparse
import hashlib
import json
import shutil
import sys

CONFIG_FILE = "build.json"
CMAKE_PATH = "CMakeLists.txt"


class Project():
    def __init__(self, name: str = None, executables: list[str] = None, executable: str = None) -> None:
        self.name: str = name or get_project_name()
        self.executables: list[str] = executables or get_executable_names(CMAKE_PATH)
        self.build_dir: str | None = None
        self.run_path: str | None = None
        self.info_msg: str | None = None
        self.executable: str | None
        if executable == "default" or executable is None:
            self.executable = self.name
        else:
            if executable in self.executables:
                self.executable = executable
            else:
                print("[ERROR]: The specificed executable is not defined in CMakeLists.txt")
                quit(1)

        self.set_os_specific()

    def display_project_info(self) -> str:
        print(beautiy("Project information"))
        print("Name: ", self.name)
        print("Executables: ", self.executables)
        print("Build directory: ", self.build_dir)
        print("Run path: ", self.run_path)

    def set_os_specific(self, exec: str = None) -> None:
        if exec:
            self.executable = exec
        if platform.system() == "Windows":
            self.info_msg = "Generating Windows build files ..."
            self.build_dir = "./build/windows"
            self.run_path = f"{self.build_dir}/Debug/{self.executable}.exe"
        elif platform.system() == "Linux":
            self.info_msg = "Generating Linux build files ..."
            self.build_dir = "./build/linux"
            self.run_path = f"{self.build_dir}/{self.executable}"
        else:
            print("[ERROR]: Unsupported platform.")
            quit(1)


def read_build_conf(file_path: str) -> dict[str, any]:
    """Read build config file and return json obj"""
    config = ""
    with open(file_path, "r", encoding="utf-8") as file:
        config = json.load(file)

    return config


def update_build_conf() -> None:
    """Updates build config with the current file hash of CMakeLists.txt"""
    config = {
        "cmakelists_hash": get_file_hash(CMAKE_PATH)
    }
    with open(CONFIG_FILE, "w", encoding="utf-8") as file:
        json.dump(config, file)


def file_changed_in_git(file_name: str) -> str:
    """Return True if file has been modified since last commit, otherwise False"""
    result1 = subprocess.run(["git", "rev-parse", f"HEAD:{file_name}"])
    hash_output1 = result1.stdout.strip()
    result2 = subprocess.run(["git", "hash-object", file_name])
    hash_output2 = result2.stdout.strip()
    return hash_output1 == hash_output2


def get_file_hash(file_path: str) -> str:
    """Gets file hash (in sha1) of the given file path"""
    BUF_SIZE = 65536  # lets read stuff in 64kb chunks!

    sha1 = hashlib.sha1()

    with open(file_path, 'rb') as f:
        while True:
            data = f.read(BUF_SIZE)
            if not data:
                break
            sha1.update(data)

    return sha1.hexdigest()


def get_project_name() -> str:
    """Get the project name defined in the CMakelists.txt file (in project(_))"""
    with open(CMAKE_PATH, encoding="utf-8") as file:
        data = file.read()

    project_name_pattern = re.compile(r"^\s*project\s*\(\s*(.+)\s*\)\s*", re.M)
    project_name_match = project_name_pattern.search(data)

    if project_name_match:
        return project_name_match.group(1)
    else:
        raise Exception("Could not find the project name in CMakeLists.txt")


def check_cmakelists_exists() -> bool:
    """Return True if CMakeLists.txt exists, otherwise False"""
    return os.path.exists(CMAKE_PATH)


def check_cache_exists() -> bool:
    """Return True if CMakeCache.txt exists, otherwise False"""
    return os.path.exists("CMakeCache.txt")


def beautiy(s: str) -> str:
    """Return decoration around a string"""
    return f"|---- {s} ----|"


def rmtree_error_handler(func, path, exc_info):
    """
    Error handler for ``shutil.rmtree``.

    If the error is due to an access error (read only file)
    it attempts to add write permission and then retries.

    If the error is for another reason it re-raises the error.
    """
    import stat
    # Is the error an access error?
    if not os.access(path, os.W_OK):
        os.chmod(path, stat.S_IWUSR)
        func(path)
    else:
        raise


def check_cmake_exists() -> bool:
    """Return True if cmake command is found, otherwise False"""
    try:
        subprocess.check_output(["cmake"])
        return True
    except Exception:
        return False


def is_cmake_variable(string: str) -> bool:
    """Return True if string is of this pattern ${variable}, otherwise False"""
    variable_pattern = re.compile(r"\s*(\$\{\S+\})\s*")
    match = variable_pattern.search(string)

    if match:
        return True
    else:
        return False


def prepend_directory(path: str, dir: str) -> str:
    """Prepend directory to path to a file, for example: ("path/cmakelists.txt", "dir") -> "path/dir/cmakelists.txt\""""
    path_list = path.split("/")
    suffix = path_list[len(path_list) - 1]
    prefix_list = path_list[:len(path_list) - 1]

    prefix = ""
    if len(prefix_list) > 1:
        prefix = "/".join(prefix_list)
    if len(prefix_list) == 1:
        prefix = prefix_list[0]
    if len(prefix_list) > 0:
        prefix += "/"

    return f"{prefix}{dir}/{suffix}"


def get_executable_names(path: str) -> list[str]:
    """Get a list of defined the defined executable names from the given CMakeLists.txt"""
    with open(path, encoding="utf-8") as file:
        lines = file.readlines()

    executables = []
    for line in lines:
        # Ignore comment lines
        if line.startswith("#"):
            continue

        # Search for subdirectory definitions to search for defined executables there as well
        subdirectory_pattern = re.compile(r"\s*add_subdirectory\s*\(\s*(.+)\s*\)\s*")
        subdirectory_match = subdirectory_pattern.match(line)
        if subdirectory_match:
            subdirectory = subdirectory_match.group(1)
            new_path = prepend_directory(path, subdirectory)

            executables.extend(get_executable_names(new_path))

        project_name_pattern = re.compile(r"\s*add_executable\s*\(\s*(\S+)\s+(.+)\s*\)\s*")
        project_name_match = project_name_pattern.match(line)

        try:
            name = project_name_match.group(1)
            if name == "${PROJECT_NAME}":
                executables.append(get_project_name())
            else:
                executables.append(name)
        except Exception:
            continue

    return executables


###########################################################################

def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description="CMake building tool")
    parser.add_argument("-r", "--run", dest="executable", help="run the project, or provided executable name", nargs="?", default=None, const="default")
    parser.add_argument("-f", "--force", action="store_true", help="force run old binary if build failed")
    parser.add_argument("-d", "--delete", action="store_true", help="delete build directory before building")
    parser.add_argument("-cm", "--cmake-options", dest="cmake_options", help="pass cmake options with -cm=\"\"", nargs=1)
    parser.add_argument("-i", "--info", action="store_true", help="display project info")
    args, other_args = parser.parse_known_args()

    # Quit if CMakeLists.txt is missing
    if not check_cmakelists_exists():
        print("[ERROR]: CMakeLists.txt is missing!")
        print("Please make sure your project is defined in it, before you run this script!")
        return 1

    # Quit if the CMake tool is not installed
    if not check_cmake_exists():
        print("[ERROR]: CMake is not installed or not in the PATH.")
        return 1

    # Create Project object with specified executable --run argument, otherwise project name is used
    project = Project(executable=args.executable)

    # Display project info
    if args.info:
        project.display_project_info()
        return 0

    # Remove "--" to pass all other arguments after it to the executable
    if "--" in other_args:
        idx = other_args.index("--")
        other_args.pop(idx)

    # Get cmake options to pass to
    if args.cmake_options:
        cmake_options = args.cmake_options
        cmake_options: list(str) = cmake_options[0].split()
    else:
        cmake_options = []

    # To save if CMakeLists.txt is modified
    modified = False

    # Create build config file to store file hash
    # in order to check if it has been modified
    if not os.path.exists(CONFIG_FILE):
        print(beautiy(f"Creating {CONFIG_FILE} file..."))
        update_build_conf()

    build_conf = read_build_conf(CONFIG_FILE)
    if build_conf["cmakelists_hash"] != get_file_hash(CMAKE_PATH):
        print(beautiy("CMakeLists.txt was changed!"))
        print(beautiy(f"Saving new file hash to {CONFIG_FILE}"))
        modified = True
        update_build_conf()

    # Get the project name defined from CMakelists.txt
    project_name = get_project_name()

    # Delete build directory if switch -d was given
    if os.path.exists(project.build_dir) and args.delete:
        print(beautiy(f"Deleting {project.build_dir}"))
        shutil.rmtree(project.build_dir, onerror=rmtree_error_handler)

    cache_file = os.path.join(project.build_dir, "CMakeCache.txt")

    proc = None
    # If the CMakeCache.txt doesn't exist or it was modified then generate cache
    if not os.path.exists(cache_file) or modified:
        print(beautiy(f"Configuring project: {project_name} ..."))
        print(beautiy(project.info_msg))
        print(beautiy("Generating CMake cache ..."))
        subprocess.run(["cmake", ".", "-B", project.build_dir] + cmake_options)

    print(beautiy(f"Building project: {project_name} ..."))
    proc = subprocess.run(["cmake", "--build", project.build_dir] + cmake_options)
    if proc.returncode != 0:
        print(beautiy("Build process failed!"))
        # If there was an error and -f switch wasn't given, quit
        if not args.force:
            return 1

    # Run project if switch was given
    if args.executable:
        if proc is not None and proc.returncode != 0:
            run_msg = "[old] "
        else:
            run_msg = ""
        print(beautiy(f"Running {run_msg}{project_name}"))
        subprocess.run([project.run_path] + other_args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
