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

BUILD_CONFIG = "build.json"
CMAKE = "CMakeLists.txt"
CMAKE_CACHE = "CMakeCache.txt"

SOURCE_FORMAT = "bash -c 'source {} ; {}'"

class Project():
    def __init__(self, name: str | None = None, executable: str | None = None, dir: str = ".", root: "Project" = None) -> None:
        self.root = root # defines root/main project
        self.cmake_path: str = os.path.join(dir, CMAKE)
        self.name: str = name or get_project_name(self.cmake_path)
        self.dir: str = dir
        self.executables: list[str] = self.get_executable_names(self.cmake_path)
        self.subprojects: dict[str, Project] = self.get_subprojects(self.cmake_path)
        self.build_dir: str
        self.executables_paths: dict[str, str]
        self.executables_dir: str
        self.run_path: str
        self.info_msg: str
        self.executable: str

        self.set_os_specific()

        # Assign executable path for each executable (and for each sub project)
        exec_paths: dict = {exec: os.path.join(self.executables_dir, exec) for exec in self.executables}
        for proj in self.subprojects.values():
            exec_paths.update({exec: os.path.join(proj.executables_dir, exec) for exec in proj.executables})

        self.executables_paths = exec_paths

        # Add all executables of subprojects in the project
        for proj in self.subprojects.values():
            self.executables.extend(proj.executables)

        if executable == "default" or executable is None:
            self.executable = self.name
        else:
            if executable in self.executables:
                self.executable = executable
            else:
                print("[ERROR]: The specificed executable is not defined in CMakeLists.txt", file=sys.stderr)
                quit(1)

        self.set_exec_ext()
        self.run_path = self.executables_paths[self.executable]

    def display_project_info(self) -> None:
        """Print out relevant project information"""
        print(beautiy("Project information"))
        print("Name: ", self.name)
        print("Build directory: ", self.build_dir)
        print("Executables directory: ", self.executables_dir)
        print("Run path: ", self.run_path)
        print("Executables: ", self.executables)
        if self.subprojects:
            print("Sub projects executables: ", {proj.name: proj.executables for proj in self.subprojects.values()})
            print("Sub projects executables directory: ", {proj.name: proj.executables_dir for proj in self.subprojects.values()})
        print("Executables paths: ", self.executables_paths)

    def set_os_specific(self) -> None:
        """Sets OS specific variables (build related)"""
        if platform.system() == "Windows":
            self.info_msg = "Generating Windows build files ..."
            if self.root:
                self.build_dir = os.path.join(self.root.dir, "build\\windows\\")
                self.executables_dir = os.path.join(self.build_dir, "Debug", os.path.relpath(self.dir) if self.dir != "." else "")
            else:
                self.build_dir = os.path.join(self.dir, "build\\windows\\")
                self.executables_dir = os.path.join(self.build_dir, "Debug\\")
        elif platform.system() == "Linux":
            self.info_msg = "Generating Linux build files ..."
            if self.root:
                self.build_dir = os.path.join(self.root.dir, "build/linux/")
                self.executables_dir = os.path.join(self.build_dir, os.path.relpath(self.dir) if self.dir != "." else "")
            else:
                self.build_dir = os.path.join(self.dir, "build/linux/")
                self.executables_dir = os.path.join(self.build_dir)
        else:
            print("[ERROR]: Unsupported platform.", file=sys.stderr)
            quit(1)

    def set_exec_ext(self) -> None:
        """Sets executable extension depending on the OS"""
        if platform.system() == "Windows":
            for exec in self.executables_paths:
                path = self.executables_paths[exec]
                self.executables_paths[exec] = f"{path}.exe"

    def set_run_path(self) -> None:
        """Sets run path for the project (OS specific)"""
        if platform.system() == "Windows":
            self.run_path = os.path.join(self.build_dir, "Debug", os.path.dirname(self.dir), f"{self.executable}.exe")
        elif platform.system() == "Linux":
            self.run_path = os.path.join(self.build_dir, os.path.dirname(self.dir), self.executable)
        else:
            print("[ERROR]: Unsupported platform.", file=sys.stderr)
            quit(1)
    
    def get_subprojects(self, file_path: str) -> dict:
        """Get a dict of Projects that are defined in subdirectories of the Project"""
        subprojects = {}

        with open(file_path, encoding="utf-8") as file:
            lines = file.readlines()

        for line in lines:
            # Search for project definition
            project_pattern = re.compile(r"^\s*project\s*\(\s*(.+)\s*\)\s*")
            project_match = project_pattern.match(line)
            if project_match:
                project_name = project_match.group(1)
                if project_name != self.name:
                    if self.root:
                        subprojects[project_name] = Project(project_name, dir=os.path.dirname(file_path), root=self.root)
                    else:
                        subprojects[project_name] = Project(project_name, dir=os.path.dirname(file_path), root=self)

            # Search for subdirectory definitions to search for defined projects there as well
            subdirectory_pattern = re.compile(r"\s*add_subdirectory\s*\(\s*(.+)\s*\)\s*")
            subdirectory_match = subdirectory_pattern.match(line)
            if subdirectory_match:
                subdirectory = subdirectory_match.group(1)

                new_path = os.path.join(os.path.dirname(file_path), subdirectory, CMAKE)

                # Recursive call of the function
                subprojects.update(self.get_subprojects(new_path))

        return subprojects

    def get_executable_names(self, file_path: str) -> list[str]:
        """Get a list of defined the defined executable names from the given CMakeLists.txt"""
        with open(file_path, encoding="utf-8") as file:
            lines = file.readlines()

        executables = []
        for line in lines:
            # Ignore comment lines
            if line.startswith("#"):
                continue

            # Search for project definition, return if project definition found
            # Sub projects executables will be handled with creation of projects through get_subprojects()
            project_pattern = re.compile(r"^\s*project\s*\(\s*(.+)\s*\)\s*")
            project_match = project_pattern.match(line)
            if project_match:
                project_name = project_match.group(1)
                if project_name != self.name:
                    return executables

            # Search for subdirectory definitions to search for defined executables there as well
            subdirectory_pattern = re.compile(r"\s*add_subdirectory\s*\(\s*(.+)\s*\)\s*")
            subdirectory_match = subdirectory_pattern.match(line)
            if subdirectory_match:
                subdirectory = subdirectory_match.group(1)

                new_path = os.path.join(os.path.dirname(file_path), subdirectory, CMAKE)

                # Recursive call of the function
                executables.extend(self.get_executable_names(new_path))
                continue

            # Search for executable definition
            executable_name_pattern = re.compile(r"\s*add_executable\s*\(\s*(\S+)\s+(.+)\s*\)\s*")
            executable_name_match = executable_name_pattern.match(line)

            if executable_name_match:
                name = executable_name_match.group(1)
                if name == "${PROJECT_NAME}":
                    executables.append(get_project_name(file_path))
                else:
                    executables.append(name)

        return executables


def read_build_conf(file_path: str) -> dict:
    """Read build config file and return json obj"""
    config = ""
    with open(file_path, "r", encoding="utf-8") as file:
        config = json.load(file)
    
    return config

def update_build_conf(file_path: str, cmake_path: str) -> None:
    """Updates build config with the current file hash of CMakeLists.txt"""
    config = {
        "cmakelists_hash": get_file_hash(cmake_path)
    }
    with open(file_path, "w", encoding="utf-8") as file:
        json.dump(config, file)

def file_changed_in_git(file_name: str) -> bool:
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

def get_project_name(file_path: str) -> str:
    """Get the project name defined in the CMakelists.txt file (in project(_))"""
    with open(file_path, encoding="utf-8") as file:
        data = file.read()

    project_name_pattern = re.compile(r"^\s*project\s*\(\s*(.+)\s*\)\s*", re.M)
    project_name_match = project_name_pattern.search(data)

    if project_name_match:
        return project_name_match.group(1)
    else:
        raise Exception("Could not find the project name in CMakeLists.txt")

def check_cmakelists_exists(file_path: str) -> bool:
    """Return True if CMakeLists.txt exists, otherwise False"""
    return os.path.exists(file_path)

def check_cache_exists() -> bool:
    """Return True if CMakeCache.txt exists, otherwise False"""
    return os.path.exists(CMAKE_CACHE)

def beautiy(s: str) -> str:
    """Return decoration around a string"""
    return f"|---- {s} ----|"

def rmtree_error_handler(func, path, exc_info):
    """
    Error handler for ``shutil.rmtree``.

    If the error is due to an access error (read only file)
    it attempts to add write permission and then retries.

    If the error is for another reason it re-raises the error.
    
    Usage : ``shutil.rmtree(path, onerror=onerror)``
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
    except:
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

def escape_quotes(string: str) -> str:
    """Return the same string with all quotes escaped in it"""
    result = string
    result = re.sub(r'"', r'\"', result)
    result = re.sub(r"'", r"\'", result)
    return result

def get_quoted_string(strings: str | list[str], all=False) -> str:
    """
    Return quoted string with all quotes in the string escaped, from a list of strings.
    @all can be specified, to quote each string. Otherwise it will only quote the the strings 
    """
    if isinstance(strings, str):
        escaped_strings = escape_quotes(strings)
    else:
        escaped_strings = escape_quotes(" ".join(strings))

    if all:
        quoted_string = " ".join([fr'"{item}"' for item in escaped_strings.split(" ")])
    else:
        quoted_string = " ".join([fr'"{item}"' if ('"' in item) or ("'" in item) else item for item in escaped_strings.split(" ")])
        
    return quoted_string

###########################################################################

def main():
    # Parse arguments
    parser = argparse.ArgumentParser(description="CMake building tool")
    parser.add_argument("--path", help="path to project to build", nargs="?", default=".", const=".")
    parser.add_argument("-r", "--run", dest="executable", help="run the project, or provided executable name", nargs="?", default=None, const="default")
    parser.add_argument("-f", "--force", action="store_true", help="force run old binary if build failed")
    parser.add_argument("-d", "--delete", action="store_true", help="delete build directory before building")
    parser.add_argument("-cm", "--cmake-options", dest="cmake_options", help="pass cmake options with -cm=\"\"", nargs=1)
    parser.add_argument("-p", "--project", action="store_true", help="display project info")
    parser.add_argument("-i", "--ignore", action="store_true", help="ignore changes in CMakeLists.txt (useful in big projects)")
    parser.add_argument("--source", help="path to file to source before building/running (linux only)", nargs="?", default="", const="")
    parser.add_argument("-b", "--binary-dir", help="path to the folder to copy the executables (binaries) to", nargs="?", default=None)

    args, other_args = parser.parse_known_args()

    cmake_path = os.path.join(args.path, CMAKE)
    build_conf_path = os.path.join(args.path, BUILD_CONFIG)

    # Quit if CMakeLists.txt is missing
    if not check_cmakelists_exists(cmake_path):
        print("[ERROR]: CMakeLists.txt is missing!", file=sys.stderr)
        print("Please make sure your project is defined in it, before you run this script!", file=sys.stderr)
        return 1
    
    # Quit if the CMake tool is not installed
    if not check_cmake_exists():
        print("[ERROR]: CMake is not installed or not in the PATH.", file=sys.stderr)
        return 1

    # Create Project object with specified executable --run argument, otherwise project name is used
    project = Project(executable=args.executable, dir=args.path)

    # Display project info
    if args.project:
        project.display_project_info()
        return 0

    # Remove "--" to pass all other arguments after it to the executable
    if "--" in other_args:
        idx = other_args.index("--")
        other_args.pop(idx)
    
    # Get cmake options to pass to
    if args.cmake_options:
        cmake_options = args.cmake_options
        cmake_options = cmake_options[0].split()
    else:
        cmake_options = []

    # To save if CMakeLists.txt is modified
    modified = False

    # Create build config file to store file hash
    # in order to check if it has been modified
    if not os.path.exists(build_conf_path):
        print(beautiy(f"Creating {build_conf_path} file..."))
        with open(build_conf_path, "w") as f:
            json.dump({}, f)
        update_build_conf(build_conf_path, cmake_path)

    # Ignore changes in CMakeLists.txt
    if not args.ignore:
        build_conf = read_build_conf(build_conf_path)
        if "cmakelists_hash" in build_conf:
            if build_conf["cmakelists_hash"] != get_file_hash(cmake_path):
                print(beautiy("CMakeLists.txt was changed!"))
                print(beautiy(f"Saving new file hash to {build_conf_path}"))
                modified = True
                update_build_conf(build_conf_path, cmake_path)
        else:
            update_build_conf(build_conf_path, cmake_path)

    # Get the project name defined from CMakelists.txt
    project_name = get_project_name(cmake_path)

    # Delete build directory if switch -d was given
    if os.path.exists(project.build_dir) and args.delete:
        print(beautiy(f"Deleting {project.build_dir}"))
        shutil.rmtree(project.build_dir, onerror=rmtree_error_handler)

    cache_file = os.path.join(project.build_dir, CMAKE_CACHE)

    if args.source:
        # Return if --source was executed on windows
        if platform.system() == "Windows":
            print("[ERROR]: Sourcing (--source) a file is currently not supported on Windows.", file=sys.stderr)
            return 1
        source_cmd = SOURCE_FORMAT
    else:
        source_cmd = "{}{}"

    proc = None
    # If the CMakeCache.txt doesn't exist or it was modified then generate cache
    if not os.path.exists(cache_file) or modified:
        print(beautiy(f"Configuring project: {project_name} ..."))
        print(beautiy(project.info_msg))
        print(beautiy("Generating CMake cache ..."))
        subprocess.run(source_cmd.format(args.source, " ".join(["cmake", args.path, "-B", project.build_dir] + cmake_options)), shell=True)

    print(beautiy(f"Building project: {project_name} ..."))
    proc = subprocess.run(source_cmd.format(args.source, " ".join(["cmake", "--build", project.build_dir])), shell=True)
    if proc.returncode != 0:
        print(beautiy("Build process failed!"), file=sys.stderr)
        # If there was an error and -f switch wasn't given, quit
        if not args.force:
            return proc.returncode
    
    if proc.returncode == 0 and args.binary_dir:
        for exec_path in project.executables_paths.values():
            binary_path = args.binary_dir
            os.makedirs(binary_path, exist_ok=True)
            shutil.copyfile(exec_path, os.path.join(binary_path, os.path.basename(exec_path)))

    # Run project if switch was given
    if args.executable:
        if proc is not None and proc.returncode != 0:
            run_msg = "[old] "
        else:
            run_msg = ""
        print(beautiy(f"Running {run_msg}{project_name}"))

        raw_other_args = get_quoted_string(other_args)
        if args.executable == "default":
            proc = subprocess.run(source_cmd.format(args.source, " ".join([project.run_path, raw_other_args])), shell=True)
        else:
            proc = subprocess.run(source_cmd.format(args.source, " ".join([project.executables_paths[args.executable], raw_other_args])), shell=True)
        
        return proc.returncode
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
