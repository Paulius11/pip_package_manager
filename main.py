import subprocess
import sys
import importlib.metadata
import logging
from simple_term_menu import TerminalMenu
from colorama import init, Fore, Style
import os
import concurrent.futures
from typing import List, Tuple, Optional, Dict
import json
from datetime import datetime, timedelta

# Initialize colorama
init()

# Set up logging
logging.basicConfig(filename='package_manager.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Constants
CACHE_FILE = 'package_cache.json'
CACHE_EXPIRY = timedelta(hours=1)
MAX_WORKERS = 20

# Menu styling
MENU_STYLE = {
    "menu_cursor": "➤ ",
    "menu_cursor_style": ("fg_cyan", "bold"),
    "menu_highlight_style": ("bg_cyan", "fg_black"),
    "status_bar_style": ("fg_black", "bg_cyan"),
    "search_highlight_style": ("fg_black", "bg_yellow", "bold"),
}


class PackageCache:
    def __init__(self, cache_file: str):
        self.cache_file = cache_file
        self.cache = self.load()

    def load(self) -> Dict[str, Dict]:
        """Load the package information cache from file."""
        if os.path.exists(self.cache_file):
            with open(self.cache_file, 'r') as f:
                return json.load(f)
        return {}

    def save(self) -> None:
        """Save the package information cache to file."""
        with open(self.cache_file, 'w') as f:
            json.dump(self.cache, f)

    def get(self, package_name: str) -> Optional[Dict]:
        """Get package info from cache if it's not expired."""
        if package_name in self.cache:
            cached_time = datetime.fromisoformat(self.cache[package_name]['timestamp'])
            if datetime.now() - cached_time < CACHE_EXPIRY:
                return self.cache[package_name]
        return None

    def set(self, package_name: str, info: Dict) -> None:
        """Set package info in cache with current timestamp."""
        info['timestamp'] = datetime.now().isoformat()
        self.cache[package_name] = info
        self.save()


class PackageManager:
    def __init__(self):
        self.cache = PackageCache(CACHE_FILE)

    def get_installed_packages(self) -> List[importlib.metadata.Distribution]:
        """Retrieve a list of installed Python packages."""
        return list(importlib.metadata.distributions())

    def get_pypi_info(self, package_name: str) -> Optional[Dict]:
        """Fetch package information from PyPI."""
        try:
            output = subprocess.check_output([sys.executable, '-m', 'pip', 'index', 'versions', package_name],
                                             stderr=subprocess.DEVNULL)
            versions = output.decode().split('Available versions: ')[-1].strip().split(', ')
            return {"latest_version": versions[0], "all_versions": versions} if versions else None
        except subprocess.CalledProcessError:
            return None

    def get_package_info(self, package: importlib.metadata.Distribution) -> Tuple[str, str, Optional[str]]:
        """Fetch or retrieve from cache the package information."""
        name = package.metadata['Name']
        installed_version = package.version

        pypi_info = self.cache.get(name)
        if not pypi_info:
            pypi_info = self.get_pypi_info(name)
            if pypi_info:
                self.cache.set(name, pypi_info)

        latest_version = pypi_info['latest_version'] if pypi_info else None
        return (name, installed_version, latest_version)

    def display_packages(self, packages: List[importlib.metadata.Distribution]) -> List[str]:
        """Create a formatted list of packages for display in the menu."""
        print("Fetching package information...")

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            package_info = list(executor.map(self.get_package_info, packages))

        menu_items = []
        max_name_length = max(len(name) for name, _, _ in package_info)
        max_version_length = max(max(len(str(installed)), len(str(latest) or ''))
                                 for _, installed, latest in package_info)

        for name, installed_version, latest_version in package_info:
            name_formatted = name.ljust(max_name_length)
            installed_formatted = str(installed_version).rjust(max_version_length)

            if latest_version and latest_version != installed_version:
                latest_formatted = str(latest_version).rjust(max_version_length)
                status = f"{name_formatted} {installed_formatted} → {latest_formatted}"
            else:
                status = f"{name_formatted} {installed_formatted}"

            menu_items.append(status)

        clear_screen()
        return menu_items

    def upgrade_package(self, package_name: str) -> bool:
        """Upgrade a package to its latest version."""
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--upgrade', package_name])
            logging.info(f"Successfully upgraded {package_name}")
            print(f"{Fore.GREEN}Successfully upgraded {package_name}{Style.RESET_ALL}")
            return True
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to upgrade {package_name}: {str(e)}")
            print(f"{Fore.RED}Failed to upgrade {package_name}{Style.RESET_ALL}")
            input("Press Enter to continue...")
            return False

    def downgrade_package(self, package_name: str) -> bool:
        """Downgrade a package to a selected earlier version."""
        print(f"Fetching available versions for {package_name}...")
        pypi_info = self.cache.get(package_name) or self.get_pypi_info(package_name)

        if not pypi_info:
            print(f"{Fore.RED}No versions available for {package_name}{Style.RESET_ALL}")
            input("Press Enter to continue...")
            return False

        versions = ["Back"] + pypi_info['all_versions']
        current_version = next((p.version for p in self.get_installed_packages() if p.metadata['Name'] == package_name),
                               None)

        terminal_menu = TerminalMenu(
            versions,
            title=f"Select version to downgrade {package_name} (Current: {current_version})",
            **MENU_STYLE
        )

        while True:
            choice_index = terminal_menu.show()

            if choice_index is None or versions[choice_index] == "Back":
                return False

            version = versions[choice_index]
            if self.install_specific_version(package_name, version):
                return True

    def install_specific_version(self, package_name: str, version: str) -> bool:
        """Install a specific version of a package."""
        try:
            print(f"Attempting to install {package_name}=={version}")
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'install', f'{package_name}=={version}'],
                check=True,
                capture_output=True,
                text=True
            )
            logging.info(f"Successfully installed {package_name} version {version}")
            print(f"{Fore.GREEN}Successfully installed {package_name} version {version}{Style.RESET_ALL}")
            return True
        except subprocess.CalledProcessError as e:
            error_message = e.stderr if e.stderr else str(e)
            logging.error(f"Failed to install {package_name} version {version}: {error_message}")
            print(f"{Fore.RED}Failed to install {package_name} version {version}{Style.RESET_ALL}")
            print(f"Error: {error_message}")
            print("Please try a different version.")
            input("Press Enter to continue...")
            return False

    def uninstall_package(self, package_name: str) -> bool:
        """Uninstall a package."""
        try:
            subprocess.check_call([sys.executable, '-m', 'pip', 'uninstall', '-y', package_name])
            logging.info(f"Successfully uninstalled {package_name}")
            print(f"{Fore.GREEN}Successfully uninstalled {package_name}{Style.RESET_ALL}")
            return True
        except subprocess.CalledProcessError as e:
            logging.error(f"Failed to uninstall {package_name}: {str(e)}")
            print(f"{Fore.RED}Failed to uninstall {package_name}{Style.RESET_ALL}")
            input("Press Enter to continue...")
            return False


def clear_screen() -> None:
    """Clear the console screen."""
    os.system('cls' if os.name == 'nt' else 'clear')


def package_options(manager: PackageManager, package_name: str) -> bool:
    """Display and handle options for a specific package."""
    while True:
        options = ["Upgrade", "Downgrade", "Uninstall", "Back"]
        terminal_menu = TerminalMenu(
            options,
            title=f"Options for {package_name}",
            **MENU_STYLE
        )
        choice_index = terminal_menu.show()

        if choice_index is None or options[choice_index] == "Back":
            return False

        choice = options[choice_index]
        if choice == "Upgrade" and manager.upgrade_package(package_name):
            return True
        elif choice == "Downgrade" and manager.downgrade_package(package_name):
            return True
        elif choice == "Uninstall" and manager.uninstall_package(package_name):
            return True


def main() -> None:
    """Main function to run the package manager."""
    manager = PackageManager()

    while True:
        clear_screen()
        packages = manager.get_installed_packages()
        menu_items = manager.display_packages(packages)
        menu_items.append("Quit")

        # Create a copy of MENU_STYLE and update it with search-specific settings
        menu_style = MENU_STYLE.copy()
        menu_style.update({
            "search_highlight_style": ("fg_red", "bold"),
        })

        terminal_menu = TerminalMenu(
            menu_items,
            title="Python Package Manager",
            search_key="/",
            show_search_hint=True,
            **menu_style
        )
        choice_index = terminal_menu.show()

        if choice_index is None or menu_items[choice_index] == "Quit":
            print("Exiting the package manager.")
            break

        selected_package = packages[choice_index].metadata['Name']
        if package_options(manager, selected_package):
            continue  # Refresh main menu


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nProgram interrupted. Exiting gracefully.")
        sys.exit(0)