import paramiko
import random
import time
import requests
import socket
import logging
import json
import os
import shutil
import tempfile
from selenium import webdriver
import atexit


class google_chrome_driver():

    def __init__(self, wait=True, initial='https://data.gov.il', chromedriver='/usr/local/bin/chromedriver'):
        if wait:
            time.sleep(random.randint(1, 600))
        self.hostname = 'tzabar.obudget.org'
        self.hostname_ip = socket.gethostbyname(self.hostname)
        username = 'adam'
        self.port = random.randint(20000, 30000)
        # print('Creating connection for client #{}'.format(self.port))

        atexit.register(self.teardown)

        self.client = paramiko.SSHClient()
        self.client.load_system_host_keys()
        self.client._policy = paramiko.WarningPolicy()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        self.client.connect(username=username, hostname=self.hostname)

        count_cmd = 'docker ps'
        while wait:
            stdin, stdout, stderr = self.client.exec_command(count_cmd)
            containers = stdout.read().decode('ascii').split('\n')
            running = len([x for x in containers if 'google-chrome' in x])
            if running < 6:
                break
            logging.info('COUNTED %d running containers, waiting', running)
            time.sleep(60)

        cmd = f'docker run -p {self.port}:{self.port} -p {self.port+1}:{self.port+1} --add-host stats.tehila.gov.il:127.0.0.1 -d akariv/google-chrome-in-a-box {self.port} {self.port+1} {initial}'
        stdin, stdout, stderr = self.client.exec_command(cmd)

        self.docker_container = None
        while not self.docker_container:
            time.sleep(3)
            self.docker_container = stdout.read().decode('ascii').strip()

        time.sleep(45)
        try:
            windows = None
            for i in range(10):
                time.sleep(6)
                try:
                    windows = requests.get(f'http://{self.hostname_ip}:{self.port}/json/list').json()
                    if len(windows) == 1:
                        break
                    logging.info('GOT %d WINDOWS: %r', len(windows), windows)
                except Exception as e:
                    logging.error('Waiting %s (%s): %s', i, windows, e)

            chrome_options = webdriver.ChromeOptions()
            chrome_options.debugger_address = f'{self.hostname_ip}:{self.port}'
            self.driver = webdriver.Chrome(chromedriver, options=chrome_options)
        except Exception:
            logging.exception('Error in setting up')
            self.teardown()

    def teardown(self):
        # print('Closing connection for client #{}'.format(self.port))
        if self.docker_container:
            try:
                stdin, stdout, stderr = self.client.exec_command(f'docker stop {self.docker_container}')
                stdout.read()
            except:
                logging.warning('FAILED to teardown google-chrome')
        try:
            self.client.close()
        except:
            logging.warning('FAILED to close connection')

    def json(self, url):
        self.driver.get(url)
        time.sleep(1)
        return json.loads(self.driver.find_element_by_css_selector('body > pre').text)

    def list_downloads(self):
        cmd = f'docker exec {self.docker_container} ls -la /downloads/'
        _, stdout, _ = self.client.exec_command(cmd)
        logging.info('CURRENT DOWNLOADS:\n%s', stdout.read().decode('utf8'))
        cmd = f'docker exec {self.docker_container} ls -1 /downloads/'
        _, stdout, _ = self.client.exec_command(cmd)
        return stdout.read().decode('utf8').split('\n')

    def download(self, url, any_file=False, format=''):
        expected = None
        if not any_file:
            expected = os.path.basename(url)
            expected = expected.split('?')[0]
        logging.info('EXPECTING: %r', expected)
        for attempt in range(3):
            logging.info('Attempt %d', attempt)
            current_downloads = self.list_downloads()
            downloads = []
            timeout = 0
            downloading = False
            self.driver.get(url)
            while True:
                time.sleep(60)
                timeout += 1

                downloads = self.list_downloads()
                logging.info('DOWNLOADS: %r', downloads)
                downloading = any('crdownload' in download for download in downloads)
                if expected is None and len(downloads) > len(current_downloads):
                    diff = set(downloads) - set(current_downloads)
                    while len(diff) > 0:
                        candidate = diff.pop()
                        if 'crdownload' not in candidate:
                            expected = candidate
                            logging.info('GOT FILENAME: %s', expected)
                            break

                if expected in downloads:
                    logging.info('found {} in {}'.format(expected, downloads))
                    time.sleep(20)
                    out = tempfile.NamedTemporaryFile(delete=False, suffix=expected + format)
                    url = f'http://{self.hostname}:{self.port+1}/{expected}'
                    response = requests.get(url, stream=True, timeout=30)
                    assert response.status_code == 200
                    stream = response.raw
                    shutil.copyfileobj(stream, out)
                    out.close()
                    logging.info('DELETE %s', requests.delete(url).text)
                    return out.name

                if not downloading:
                    logging.info('TIMED OUT while NOT downloading')
                    break

                # if timeout > 30 and downloading:
                #     logging.info('TIMED OUT while downloading')
                #     break

        assert False, 'Failed to download file, %r' % downloads


def finalize(f):
    def func(package):
        yield package.pkg
        yield from package
        try:
            logging.warning('Finalizing connection')
            f()
        except Exception:
            logging.exception('Failed to finalize')
    return func



if __name__ == '__main__':
    gcd = google_chrome_driver()
    c = gcd.driver
    c.get('http://data.gov.il/api/action/package_search')
    time.sleep(2)
    print(c.find_element_by_css_selector('body > pre').text)
    gcd.teardown()
