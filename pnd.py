ver = "0.9.9.7"
import appdaemon.plugins.hass.hassapi as hass
import time
import os
import math
import shutil
import pandas as pd
import zipfile
from datetime import datetime as dt, timedelta
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from bs4 import BeautifulSoup
import platform
import subprocess

def get_timestamp():
    return dt.now().strftime("%Y-%m-%d %H:%M:%S")

def log(message):
    print(f"{get_timestamp()}: {message}")

def print_system_info():
    log(f"""System Information:
    ===================
    Platform: {platform.system()}
    Platform Release: {platform.release()}
    Platform Version: {platform.version()}
    Architecture: {platform.machine()}
    Processor: {platform.processor()}
    Python Version: {platform.python_version()}
    """)

def print_installed_modules():
    result = subprocess.run(['pip', 'list'], stdout=subprocess.PIPE, text=True)
    log(f"""Installed Python Modules:
    {result.stdout}
    """)

def get_chromedriver_version():
    try:
        result = subprocess.run(['chromedriver', '--version'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode == 0:
            version_info = result.stdout.strip()
            log(f"ChromeDriver Version: {version_info}")
        else:
            log(f"Error: {result.stderr.strip()}")
    except FileNotFoundError:
        log("ChromeDriver is not installed or not found in the system PATH.")

def wait_for_download(directory, timeout=30):
    seconds = 0
    dl_wait = True
    while dl_wait and seconds < timeout:
        time.sleep(1)
        files = sorted([os.path.join(directory, f) for f in os.listdir(directory)], key=os.path.getmtime)
        # Filter out incomplete downloads
        files = [f for f in files if not f.endswith('.crdownload')]
        if files:
            dl_wait = False
        seconds += 1
    if files:
        return files[-1]
    return None

def delete_folder_contents(folder_path):
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        try:
            if os.path.isfile(file_path) or os.path.islink(file_path):
                os.unlink(file_path)  # Removes each file.
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)  # Removes directories and their contents recursively.
        except Exception as e:
            print(f"Failed to delete {file_path}. Reason: {e}")


class Colors:
    RED = '\033[31m'   # Red text
    GREEN = '\033[32m' # Green text
    YELLOW = '\033[33m' # Yellow text
    BLUE = '\033[34m'  # Blue text
    MAGENTA = '\033[35m' # Magenta text
    CYAN = '\033[36m'  # Cyan text
    RESET = '\033[0m'  # Reset to default color

def zip_folder(folder_path, output_path):
    # Create a ZIP file at the specified output path
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Walk through the directory
        for root, dirs, files in os.walk(folder_path):
            for file in files:
                # Create the full path to the file
                file_path = os.path.join(root, file)
                # Write the file to the zip file
                # arcname handles the path inside the zip
                zipf.write(file_path, arcname=os.path.relpath(file_path, start=folder_path))


def quit_driver(driver):
    driver.quit()
    try:
        pid = True
        while pid:
            pid = os.waitpid(-1, os.WNOHANG)
            try:
                if pid[0] == 0:
                    pid = False
            except:
                pass
    except ChildProcessError:
        pass

def conv_date(s):
    s = s.replace("24:00:00", "23:59:00")
    return dt.strptime(s, "%d.%m.%Y %H:%M:%S")

def _normalize_ha_state(value):
    if value is None:
        return "unknown"
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return "unknown"
    if isinstance(value, timedelta):
        value = str(value)
    s = str(value)
    s = " ".join(s.replace("\xa0", " ").split())
    return s[:255]  # HA hard limit

class pnd(hass.Hass):
  def initialize(self):
    log(">>>>>>>>>>>> PND Initialize")
    print_system_info()
    print_installed_modules()
    get_chromedriver_version()

    self.username = self.args["PNDUserName"]
    self.password = self.args["PNDUserPassword"]
    self.download_folder = self.args["DownloadFolder"]
    self.datainterval = self.args["DataInterval"]
    self.ELM = self.args["ELM"]
    self.id = self.args.get("id", "")
    self.suffix = f"_{self.id}" if self.id else ""
    self.entity_id_consumption = f"sensor.pnd_consumption{self.suffix}"
    self.entity_id_production = f"sensor.pnd_production{self.suffix}"
    self.listen_event(self.run_pnd, "run_pnd")

  def terminate(self):
    log(">>>>>>>>>>>> PND Terminate")

  def set_state_safe(self, entity_id, state, attributes=None):
      return self.set_state(entity_id, state=_normalize_ha_state(state), attributes=attributes or {})

  def run_pnd(self, event_name, data, kwargs):
    script_start_time = dt.now()
    log(f"{Colors.CYAN}********************* Starting {ver} *********************{Colors.RESET}")
    self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="on")
    self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Running",attributes={
      "status": "OK",
      "friendly_name": "PND Script Status"
    })
    log("----------------------------------------------")
    log("Hello from AppDaemon for Portal Namerenych Dat")
    delete_folder_contents(self.download_folder+"/")
    os.makedirs(self.download_folder, exist_ok=True)
    chrome_options = Options()
    chrome_options.add_experimental_option("prefs", {
        "download.default_directory": self.download_folder,  # Set download folder
        "download.prompt_for_download": False,          # Disable download prompt
        "download.directory_upgrade": True,             # Manage download directory
        "plugins.always_open_pdf_externally": False      # Automatically open PDFs
    })
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument("--log-level=3")  # Disable logging
    #load service
    service = Service('/usr/bin/chromedriver')
    #load driver
    try:
      driver = webdriver.Chrome(service=service, options=chrome_options)
      log("Driver Loaded")
    except:
      log(f"{Colors.RED}ERROR: Unable to initialize Chrome Driver - exitting{Colors.RESET}")
      self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
      self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error",attributes={
        "status": "ERROR: Nepodařilo se inicializovat Chrome Driver, zkontroluj nastavení AppDaemon",
        "friendly_name": "PND Script Status"
      })
      raise Exception("Unable to initialize Chrome Driver - exitting")
    # Open a website
    driver.set_window_size(1920, 1080)
    try:
      #driver.get("https://dip.cezdistribuce.cz/irj/portal/?zpnd=")  # Change to the website's login page
      PNDURL = "https://pnd.cezdistribuce.cz/cezpnd2/external/dashboard/view"
      log(f"Opening Website: {PNDURL}")
      driver.get(PNDURL)  # Change to the website's login page
      log("Website Opened")
    except:
      log(f"{Colors.RED}ERROR: Unable to open website - exitting{Colors.RESET}")
      self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
      self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
        "status": "ERROR: Nepodařilo se otevřít webovou stránku PND portálu",
        "friendly_name": "PND Script Status"
      })
      raise Exception("Unable to open website - exitting")
    time.sleep(3)  # Allow time for the page to load
    log(f"Current URL: {driver.current_url}")
    try:
        # Locate the element that might be blocking the login button
        cookie_banner_close_button = driver.find_element(By.ID, "CybotCookiebotDialogBodyLevelButtonLevelOptinAllowallSelection")
        # Click the close button or take other action to dismiss the cookie banner
        cookie_banner_close_button.click()
    except:
        log("No cookie banner found")
        #self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
        #self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
        #    "status": "ERROR: Nepodařilo se nalézt cookie banner, zkuste za chvíli znovu spustit skript.",
        #    "friendly_name": "PND Script Status"
        #})
        #raise Exception("Unable to open website - exitting")
    time.sleep(1)  # Allow time for the page to load
    # Simulate login
    try:
        #username_field = driver.find_element(By.XPATH, "//input[@placeholder='Uživatelské jméno / e-mail']")
        username_field = driver.find_element(By.XPATH, "//input[@placeholder='Zadejte svůj e-mail']")
        #password_field = driver.find_element(By.XPATH, "//input[@placeholder='Heslo']")
        password_field = driver.find_element(By.XPATH, "//input[@placeholder='Zadejte své heslo']")
        #login_button = driver.find_element(By.XPATH, "//button[@type='submit' and @color='primary']")
        login_button = driver.find_element(By.XPATH, "//button[@type='submit' and contains(@class, 'mui-btn--primary')]")
        # Enter login credentials and click the button
        username_field.send_keys(self.username)
        password_field.send_keys(self.password)
        # Wait until the login button is clickable
        wait = WebDriverWait(driver, 10)  # 10-second timeout
        #login_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit' and @color='primary']")))
        log("Login button found, clicking it")
        login_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@type='submit' and contains(@class, 'mui-btn--primary')]")))
        body = driver.find_element(By.TAG_NAME, 'body')
        body.screenshot(self.download_folder+"/00.png")
        login_button.click()
    except:
        log(f"{Colors.RED}ERROR: Failed to enter login details or find and click the login button{Colors.RESET}")
        self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
        self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
            "status": "ERROR: Nepodařilo se vyplnit přihlašovací údaje nebo najít a kliknout na tlačítko pro přihlášení",
            "friendly_name": "PND Script Status"
        })
        raise Exception("Failed to find or click the login button")
    # Allow time for login processing
    time.sleep(5)  # Adjust as needed
    log(f"Current URL: {driver.current_url}")
    wait = WebDriverWait(driver, 20)  # 10-second timeout
    body = driver.find_element(By.TAG_NAME, 'body')
    # Check if the specified H1 tag is present
    h1_text = "Naměřená data"
    try:
        h1_element = wait.until(EC.presence_of_element_located((By.XPATH, f"//h1[contains(text(), '{h1_text}')]")))
    except:
        alert_widget_content = driver.find_element(By.CLASS_NAME, "alertWidget__content").text
        log(f"{Colors.RED}ERROR: {alert_widget_content}{Colors.RESET}")
        self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
        "status": "ERROR: Není možné se přihlásit do aplikace",
        "friendly_name": "PND Script Status"
        })
        raise Exception(f"Unable to login to the app")
    body.screenshot(self.download_folder+"/01.png")
    # Print whether the H1 tag with the specified text is found
    if h1_element:
        log(f"H1 tag with text '{h1_text}' is present.")
    else:
        log(f" {Colors.RED}ERROR: H1 tag with text '{h1_text}' is not found.{Colors.RESET}")
        self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
        self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
            "status": f"ERROR: Text '{h1_text}' nebyl nalezen na stránce, zkuste skript spustit později znovu.",
            "friendly_name": "PND Script Status"
        })
        raise Exception(f"Failed to find H1 tag with text '{h1_text}'")

    # Check for Modal Dialog
    try:
        modal_dialog = driver.find_element(By.CLASS_NAME, "modal-dialog")
        log(f"{Colors.YELLOW}Modal Dialog found{Colors.RESET}")
        # Close the modal dialog
        try:
            body.screenshot(self.download_folder+"/01-modal.png")
            log(f"{Colors.YELLOW}Closing Modal Dialog{Colors.RESET}")
            close_button = modal_dialog.find_element(By.XPATH, ".//button[contains(@class, 'btn pnd-btn btn-primary') and contains(text(), 'Přečteno')]")
            close_button.click()
            log(f"{Colors.GREEN}Modal Dialog closed successfully, reloading page{Colors.RESET}")
            time.sleep(2)  # Allow time for the modal to close
            # Reload the page after clicking the button
            driver.refresh()
            log(f"{Colors.GREEN}Page reloaded successfully{Colors.RESET}")
        except:
            log(f"{Colors.RED}ERROR: Close button not found in the modal dialog.{Colors.RESET}")
            raise Exception("Unable to click the close button in the modal dialog")
    except:
        log(f"{Colors.GREEN}Modal dialog not found. Continuing without closing modal.{Colors.RESET}")
    time.sleep(2)  # Allow time for the page to load
    # Get the app version
    version_element = driver.find_element(By.XPATH, "//div[contains(text(), 'Verze aplikace:')]")
    version_text = (version_element.get_attribute("textContent") or version_element.text or "").replace("\xa0", " ")
    parts = version_text.split(":", 1)
    version_number = parts[1].strip() if len(parts) > 1 else version_text.strip()
    version_number = str(version_number).strip() or "unknown"
    self.set_state_safe(f"sensor.pnd_app_version{self.suffix}", state=version_number, attributes={
        "friendly_name": "PND App Version",
    })
    log(f"App Version: {version_number}")

    first_pnd_window = wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, ".pnd-window")))

    # Find the button by its title attribute
    tabulka_dat_button = WebDriverWait(first_pnd_window, 10).until(
        EC.element_to_be_clickable((By.XPATH, ".//button[@title='Export']"))
    )

    tabulka_dat_button.click()

    body.screenshot(self.download_folder+"/02.png")
    # Navigate to the dropdown based on its label "Sestava"
    # Find the label by text, then navigate to the associated dropdown
    wait = WebDriverWait(driver, 2)  # Adjust timeout as necessary
    option_text = "Rychlá sestava"

    for _ in range(10):
        dropdown_label = wait.until(EC.visibility_of_element_located((By.XPATH, "//label[contains(text(), 'Sestava')]")))
        dropdown = dropdown_label.find_element(By.XPATH, "./following-sibling::div//div[contains(@class, 'multiselect__tags')]")
        dropdown.click()

        # Select the option containing the text
        option = wait.until(EC.element_to_be_clickable((By.XPATH, f"//span[contains(text(), '{option_text}')]")))
        option.click()
        body.click()
        # Check if the span contains "Rychlá sestava"
        try:
            wait.until(EC.text_to_be_present_in_element((By.XPATH, "//span[@class='multiselect__single']"), "Rychlá sestava"))
            break
        except TimeoutException:
            continue
    else:
        log(f" {Colors.RED}ERROR: Rychla Sestava neni mozne vybrat!{Colors.RESET}")
        self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
        self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
            "status": "ERROR: Nebylo možné vybrat 'Rychlá sestava' po 10 pokusech. Zkuste skript spustit později znovu.",
            "friendly_name": "PND Script Status"
        })
        raise Exception("Failed to find 'Rychlá sestava' after 10 attempts")
    log(f"{Colors.GREEN}Rychla Sestava selected successfully!{Colors.RESET}")
    body.screenshot(self.download_folder+"/03.png")

    # Check the input field value
    time.sleep(1)  # Allow any JavaScript updates

    log(f"Selecting ELM '{self.ELM}'")

    soup = BeautifulSoup(driver.page_source, 'html.parser')
    dropdown_label = wait.until(EC.visibility_of_element_located((By.XPATH, "//label[contains(text(), 'Množina zařízení')]")))
    parent_element = dropdown_label.find_element(By.XPATH, ".//ancestor::div[contains(@class, 'form-group')]")
    text = parent_element.get_attribute('outerHTML')
    elm_spans = soup.find_all('span', class_='multiselect__option', text=lambda text: text and text.startswith('ELM'))
    elm_values = [span.text for span in elm_spans]
    elm_values_string = ", ".join(elm_values)
    log(f"Valid ELM numbers '{elm_values_string}'")

    # Navigate to the dropdown based on its label "Množina zařízení"
    # Find the label by text, then navigate to the associated dropdown
    with open(self.download_folder+'/debug-ELM.txt', 'w') as file:
        file.write(">>>Debug ELM<<<"+ "\n")
    wait = WebDriverWait(driver, 2)
    dropdown_label = wait.until(EC.visibility_of_element_located((By.XPATH, "//label[contains(text(), 'Množina zařízení')]")))
    parent_element = dropdown_label.find_element(By.XPATH, ".//ancestor::div[contains(@class, 'form-group')]")
    #log(f"{Colors.CYAN}{parent_element.get_attribute('outerHTML')}{Colors.RESET}")
    with open(self.download_folder+'/debug-ELM.txt', 'a') as file:
        file.write(parent_element.get_attribute('outerHTML')+ "\n")
    dropdown = dropdown_label.find_element(By.XPATH, "./following-sibling::div//div[contains(@class, 'multiselect__select')]")  # Adjusted to the next input field within a sibling div

    for i in range(10):
        dropdown.click()  # Open the dropdown
        time.sleep(1)
        body.screenshot(self.download_folder+f"/03-{i}-a.png")
        try:
            option = wait.until(EC.element_to_be_clickable((By.XPATH, f"//span[contains(text(), '{self.ELM}')]")))
        except:
            log(f"{Colors.RED}ERROR: Failed to find '{self.ELM}' in the selection - check ELM attribute in the apps.yaml{Colors.RESET}")
            self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
            self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
                "status": f"ERROR: Nebylo možné najít '{self.ELM}' v nabídce. Zkontrolujte ELM atribut v nastavení aplikace.",
                "friendly_name": "PND Script Status"
            })
            raise Exception(f"Failed to find '{self.ELM}' in the selection")
        option.click()
        body.screenshot(self.download_folder+f"/03-{i}-b.png")
        body.click()
        button = driver.find_element(By.XPATH, "//button[contains(., 'Vyhledat data')]")
        class_attribute = button.get_attribute('class')
        try:
            span = parent_element.find_element(By.XPATH, ".//span[@class='multiselect__single']").text
        except:
            span = ''
        log(f"{Colors.CYAN}ELM Status: {span} - {self.ELM}{Colors.RESET}")
        #if 'disabled' not in class_attribute:
        parent_element = dropdown_label.find_element(By.XPATH, ".//ancestor::div[contains(@class, 'form-group')]")
        with open(self.download_folder+'/debug-ELM.txt', 'a') as file:
            file.write(f">>>Iteration {i}<<<"+ "\n")
        with open(self.download_folder+'/debug-ELM.txt', 'a') as file:
            file.write("ELM Span content: " +span+ "\n")
        with open(self.download_folder+'/debug-ELM.txt', 'a') as file:
            file.write(parent_element.get_attribute('outerHTML')+ "\n")
        if 'disabled' not in class_attribute and span.strip() != '':
            log(f"{Colors.GREEN}Iteration {i}: Vyhledat Button NOT disabled{Colors.RESET}")
            break
        else:
            log(f"{Colors.YELLOW}Iteration {i}: Vyhledat Button IS disabled{Colors.RESET}")
    else:
        log(f" {Colors.RED}ERROR: Failed to find '{self.ELM}' after 10 attempts{Colors.RESET}")
        self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
        self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
            "status": f"ERROR: Nebylo možné najít '{self.ELM}' po 10 pokusech. Zkontrolujte ELM atribut v nastavení aplikace.",
            "friendly_name": "PND Script Status"
        })
        raise Exception(f"Failed to find '{self.ELM}' after 10 attempts")
    log(f"{Colors.GREEN}Device ELM '{self.ELM}' selected successfully!{Colors.RESET}")
    body.screenshot(self.download_folder+"/04.png")

    # Navigate to the dropdown based on its label "Období"
    # Use the label text to find the dropdown button
    try:
        wait = WebDriverWait(driver, 2)
        dropdown_label = wait.until(EC.element_to_be_clickable((By.XPATH, "//label[contains(text(), 'Období')]")))
        dropdown_container = dropdown_label.find_element(By.XPATH, "./following-sibling::div//div[contains(@class, 'multiselect__select')]")
        dropdown_container.click()
        # Now, wait for the option labeled "Včera" to be visible and clickable, then click it
        wait = WebDriverWait(driver, 2)
        option_vcera = wait.until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Včera') and contains(@class, 'multiselect__option')]")))
        option_vcera.click()
    except:
        log(f"{Colors.RED}ERROR: Failed to select 'Včera' in the dropdown{Colors.RESET}")
        self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
        self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
            "status": "ERROR: Nepodařilo se vybrat 'Včera' v nabídce",
            "friendly_name": "PND Script Status"
        })
        raise Exception("Failed to select 'Včera' in the dropdown")
    body.screenshot(self.download_folder+"/05.png")
    # Check for the presence of the button and then check if it's clickable
    try:
        button = wait.until(EC.presence_of_element_located((By.XPATH, "//button[contains(., 'Vyhledat data')]")))
        button.click()
        log(f"{Colors.GREEN}Button 'Vyhledat data' clicked successfully!{Colors.RESET}")
    except Exception as e:
        log(f"{Colors.RED}Failed to find or click the 'Vyhledat data' button:{Colors.RESET} {str(e)}")
        self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
        self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
            "status": "ERROR: Nepodařilo se nalézt nebo kliknout na tlačítko 'Vyhledat data'",
            "friendly_name": "PND Script Status"
        })
        raise Exception("Failed to find or click the 'Vyhledat data' button")
    body.screenshot(self.download_folder+"/06.png")
    time.sleep(2)
    body.click()

    # Wait for the page and elements to fully load
    wait = WebDriverWait(driver, 10)  # Adjust timeout as necessary
    body.screenshot(self.download_folder+"/07.png")
    # Find and click the link by its exact text
    try:
        link_text = "07 Profil spotřeby za den (+A)"
        link = WebDriverWait(first_pnd_window, 10).until(
            EC.element_to_be_clickable((By.XPATH, ".//a[contains(text(), '" + link_text + "')]"))
        )
        log( link.text)

        # Navigate to the parent element using XPath
        parent_element = driver.execute_script("return arguments[0].parentNode;", link)
        # Get the HTML of the parent element
        parent_html = parent_element.get_attribute('outerHTML')
        time.sleep(2)
        body.screenshot(self.download_folder+"/daily-body-07a.png")
        link.click()
        body.screenshot(self.download_folder+"/daily-body-07b.png")
        body.click()
        body.screenshot(self.download_folder+"/daily-body-07c.png")
    except:
        log(f"{Colors.RED}ERROR: Failed to find link {link_text}{Colors.RESET}")
        self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
        self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
            "status": f"ERROR: Nepodařilo se najít odkaz pro denní export {link_text}",
            "friendly_name": "PND Script Status"
        })
    # Wait for the dropdown toggle and click it using the button text
    try:
        wait = WebDriverWait(driver, 10)
        toggle_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Exportovat data')]")))
        time.sleep(2)
        toggle_button.click()

        # Wait for the CSV link and click it
        csv_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[normalize-space()='CSV']")))
        log(f"Downloading CSV file for {link_text}")
        csv_link.click()
    except:
        log(f"{Colors.RED}ERROR: Failed to download CSV file for {link_text}{Colors.RESET}")
        self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
        self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
            "status": f"ERROR: Nepodařilo se stáhnout CSV soubor pro denní export {link_text}",
            "friendly_name": "PND Script Status"
        })
    # Wait for the download to complete
    time.sleep(5)
    try:
        del downloaded_file
    except:
        pass
    #downloaded_file = wait_for_download(self.download_folder)
    downloaded_file = os.path.join(self.download_folder, "pnd_export.csv")
    # Rename the file if it was downloaded
    if downloaded_file:
        new_filename = os.path.join(self.download_folder, "daily-consumption.csv")
        os.remove(new_filename) if os.path.exists(new_filename) else None
        os.rename(downloaded_file, new_filename)
        log(f"{Colors.GREEN}File downloaded and saved as: {new_filename}{Colors.RESET}")
    else:
        log(f"{Colors.RED} ERROR: No file was downloaded for {link_text}{Colors.RESET}")

    wait = WebDriverWait(driver, 10)  # Adjust timeout as necessary

    # Find and click the link by its exact text
    body.screenshot(self.download_folder+"/08.png")
    try:
        link_text = "08 Profil výroby za den (-A)"
        link = WebDriverWait(first_pnd_window, 10).until(
            EC.element_to_be_clickable((By.XPATH, ".//a[contains(text(), '" + link_text + "')]"))
        )
        log( link.text)

        # Navigate to the parent element using XPath
        parent_element = driver.execute_script("return arguments[0].parentNode;", link)
        # Get the HTML of the parent element
        parent_html = parent_element.get_attribute('outerHTML')
        time.sleep(2)
        body.screenshot(self.download_folder+"/daily-body-08a.png")
        link.click()
        body.screenshot(self.download_folder+"/daily-body-08b.png")
        body.click()
        body.screenshot(self.download_folder+"/daily-body-08c.png")
    except:
        log(f"{Colors.RED}ERROR: Failed to find link {link_text}{Colors.RESET}")
        self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
        self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
            "status": f"ERROR: Nepodařilo se najít odkaz pro denní export {link_text}",
            "friendly_name": "PND Script Status"
        })
    # Wait for the dropdown toggle and click it using the button text
    wait = WebDriverWait(driver, 10)
    try:
        toggle_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Exportovat data')]")))
        time.sleep(2)
        toggle_button.click()

        # Wait for the CSV link and click it
        csv_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[normalize-space()='CSV']")))
        log(f"Downloading CSV file for {link_text}")
        csv_link.click()

    except:
        log(f"{Colors.RED}ERROR: Failed to download CSV file for {link_text}{Colors.RESET}")
        self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
        self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
            "status": f"ERROR: Nepodařilo se stáhnout CSV soubor pro denní export{link_text}",
            "friendly_name": "PND Script Status"
        })
    # Wait for the download to complete
    time.sleep(5)
    try:
        del downloaded_file
    except:
        pass
    #downloaded_file = wait_for_download(self.download_folder)
    # Rename the file if it was downloaded
    downloaded_file = os.path.join(self.download_folder, "pnd_export.csv")
    if downloaded_file:
        new_filename = os.path.join(self.download_folder, "daily-production.csv")
        os.remove(new_filename) if os.path.exists(new_filename) else None
        os.rename(downloaded_file, new_filename)
        log(f"{Colors.GREEN}File downloaded and saved as: {new_filename}{Colors.RESET}")
    else:
        log(f"{Colors.RED} ERROR: No file was downloaded for {link_text}{Colors.RESET}")

    log("All Done - DAILY DATA DOWNLOADED")
    data_consumption = pd.read_csv(self.download_folder + '/daily-consumption.csv', delimiter=';', encoding='latin1')
    latest_consumption_entry = data_consumption.iloc[-1]  # Get the last row, assuming the data is appended daily
    data_production = pd.read_csv(self.download_folder + '/daily-production.csv', delimiter=';', encoding='latin1')
    latest_production_entry = data_production.iloc[-1]  # Get the last row, assuming the data is appended daily

    # Extract date and consumption values
    date_consumption_str = latest_consumption_entry.iloc[0]
    date_consumption_obj = conv_date(date_consumption_str)
    yesterday_consumption = date_consumption_obj - timedelta(days=1)
    date_production_str = latest_production_entry.iloc[0]
    date_production_obj = conv_date(date_production_str)
    yesterday_production = date_production_obj - timedelta(days=1)

    consumption_value = latest_consumption_entry.iloc[1]
    production_value = latest_production_entry.iloc[1]

    log(f"{Colors.GREEN}Latest entry: {date_consumption_str} - {consumption_value} kWh{Colors.RESET}")
    log(f"{Colors.GREEN}Latest entry: {date_production_str} - {production_value} kWh{Colors.RESET}")

    self.set_state(self.entity_id_consumption, state=consumption_value, attributes={
      "friendly_name": "PND Consumption",
      "device_class": "energy",
      "unit_of_measurement": "kWh",
      "date": yesterday_consumption.isoformat()
    })
    self.set_state(self.entity_id_production, state=production_value, attributes={
      "friendly_name": "PND Production",
      "device_class": "energy",
      "unit_of_measurement": "kWh",
      "date": yesterday_production.isoformat()
    })

    log("All Done - DAILY DATA PROCESSED")

    #------------------INTERVAL-----------------------------
    ## Use the label text to find the dropdown button
    try:
        dropdown_label = wait.until(EC.element_to_be_clickable((By.XPATH, "//label[contains(text(), 'Období')]")))
        dropdown_container = dropdown_label.find_element(By.XPATH, "./following-sibling::div//div[contains(@class, 'multiselect__select')]")
        dropdown_container.click()

        ## Now, wait for the option labeled "Včera" to be visible and clickable, then click it
        option_vcera = wait.until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Vlastní') and contains(@class, 'multiselect__option')]")))
        option_vcera.click()

        # Locate the input by finding the label then navigating to the input
        label = wait.until(EC.visibility_of_element_located((By.XPATH, "//label[contains(text(), 'Vlastní období')]")))
        input_field = label.find_element(By.XPATH, "./following::input[1]")  # Adjust based on actual DOM structure

        # Clear the input field first if necessary
        input_field.clear()

        # Enter the date range into the input field
        date_range = self.datainterval
        input_field.send_keys(date_range)

        # Optionally, you can send ENTER or TAB if needed to process the input
        input_field.send_keys(Keys.TAB)  # or Keys.TAB if you need to move out of the input field
        body.click()
    except:
        log(f"{Colors.RED}ERROR: Failed to select 'Vlastní období' in the dropdown{Colors.RESET}")
        self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
        self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
            "status": "ERROR: Nepodařilo se vybrat 'Vlastní období' v nabídce",
            "friendly_name": "PND Script Status"
        })
        raise Exception("Failed to select 'Vlastní období' in the dropdown")
    # Confirmation output (optional)
    log(f"Data Interval Entered - '{self.datainterval}'")
    #-----------------------------------------------
    time.sleep(1)
    try:
        tabulka_dat_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@title='Tabulka dat']")))
        # Click the button
        tabulka_dat_button.click()
        time.sleep(1)
        tabulka_dat_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@title='Export']")))
        # Click the button
        tabulka_dat_button.click()
        body.click()
    except:
        log(f"{Colors.RED}ERROR: Failed to click 'Tabulka dat' button{Colors.RESET}")
        self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
        self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
            "status": "ERROR: Nepodařilo se kliknout na tlačítko 'Tabulka dat'",
            "friendly_name": "PND Script Status"
        })
        raise Exception("Failed to click 'Tabulka dat' button")

    # Wait for the page and elements to fully load
    wait = WebDriverWait(driver, 10)  # Adjust timeout as necessary

    # Find and click the link by its exact text
    try:
        log("Selecting 07 Profil spotřeby za den (+A)")
        link_text = "07 Profil spotřeby za den (+A)"
        link = WebDriverWait(first_pnd_window, 10).until(
            EC.element_to_be_clickable((By.XPATH, ".//a[contains(text(), '" + link_text + "')]"))
        )
        log( link.text)

        # Navigate to the parent element using XPath
        parent_element = driver.execute_script("return arguments[0].parentNode;", link)
        # Get the HTML of the parent element
        parent_html = parent_element.get_attribute('outerHTML')
        # Use ActionChains to move to the element
        actions = ActionChains(driver)
        actions.move_to_element(link).perform()
        time.sleep(1)
        body.screenshot(self.download_folder+"/interval-body-07a.png")
        link.click()
        body.screenshot(self.download_folder+"/interval-body-07b.png")
        time.sleep(1)
        body.click()
    except:
        log(f"{Colors.RED}ERROR: Failed to find link {link_text}{Colors.RESET}")
        self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
        self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
            "status": f"ERROR: Nepodařilo se najít odkaz pro interval export {link_text}",
            "friendly_name": "PND Script Status"
        })

    body.screenshot(self.download_folder+"/interval-body-07c.png")

    # Wait for the dropdown toggle and click it using the button text
    log("Exporting data")
    wait = WebDriverWait(driver, 10)
    try:
        toggle_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Exportovat data')]")))
        time.sleep(1)
        toggle_button.click()

        # Wait for the CSV link and click it
        csv_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[normalize-space()='CSV']")))
        csv_link.click()
    except:
        log(f"{Colors.RED}ERROR: Failed to download CSV file for {link_text}{Colors.RESET}")
        self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
        self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
            "status": f"ERROR: Nepodařilo se stáhnout CSV soubor pro interval export {link_text}",
            "friendly_name": "PND Script Status"
        })
    # Wait for the download to complete
    time.sleep(5)
    try:
        del downloaded_file
    except:
        pass
    #downloaded_file = wait_for_download(self.download_folder)
    downloaded_file = os.path.join(self.download_folder, "pnd_export.csv")
    # Rename the file if it was downloaded
    if downloaded_file:
        new_filename = os.path.join(self.download_folder, "range-consumption.csv")
        os.remove(new_filename) if os.path.exists(new_filename) else None
        os.rename(downloaded_file, new_filename)
        downloaded_file = self.download_folder+"/range-consumption.csv"
        log(f"{Colors.GREEN}File downloaded and saved as: {new_filename} {round(os.path.getsize(downloaded_file)/1024,2)} KB{Colors.RESET}")
    else:
        log(f"{Colors.RED}ERROR: No file was downloaded.{Colors.RESET}")
    #----------------------------------------------
    # Wait for the page and elements to fully load
    wait = WebDriverWait(driver, 10)  # Adjust timeout as necessary

    # Find and click the link by its exact text
    log("Selecting 08 Profil výroby za den (-A)")
    link_text = "08 Profil výroby za den (-A)"
    try:
        link = WebDriverWait(first_pnd_window, 10).until(
            EC.element_to_be_clickable((By.XPATH, ".//a[contains(text(), '" + link_text + "')]"))
        )
        log( link.text)

        # Navigate to the parent element using XPath
        parent_element = driver.execute_script("return arguments[0].parentNode;", link)
        # Get the HTML of the parent element
        parent_html = parent_element.get_attribute('outerHTML')
        # Use ActionChains to move to the element
        actions = ActionChains(driver)
        actions.move_to_element(link).perform()

        body.screenshot(self.download_folder+"/interval-body-08a.png")
        time.sleep(1)
        link.click()
        body.screenshot(self.download_folder+"/interval-body-08b.png")
        time.sleep(1)
        body.click()
        body.screenshot(self.download_folder+"/interval-body-08c.png")
    except:
        log(f"{Colors.RED}ERROR: Failed to find link {link_text}{Colors.RESET}")
        self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
        self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
            "status": f"ERROR: Nepodařilo se najít odkaz pro interval export {link_text}",
            "friendly_name": "PND Script Status"
        })
    # Wait for the dropdown toggle and click it using the button text
    log("Exporting data")
    wait = WebDriverWait(driver, 10)
    try:
        toggle_button = wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Exportovat data')]")))
        #driver.execute_script("arguments[0].scrollIntoView();", toggle_button)

        toggle_button.click()

        # Wait for the CSV link and click it
        csv_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[normalize-space()='CSV']")))
        csv_link.click()
    except:
        log(f"{Colors.RED}ERROR: Failed to download CSV file for {link_text}{Colors.RESET}")
        self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
        self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Error", attributes={
            "status": f"ERROR: Nepodařilo se stáhnout CSV soubor pro interval export {link_text}",
            "friendly_name": "PND Script Status"
        })
    # Wait for the download to complete
    time.sleep(5)
    try:
        del downloaded_file
    except:
        pass
    #downloaded_file = wait_for_download(self.download_folder)
    downloaded_file = os.path.join(self.download_folder, "pnd_export.csv")

    # Rename the file if it was downloaded
    if downloaded_file:
        new_filename = os.path.join(self.download_folder, "range-production.csv")
        os.remove(new_filename) if os.path.exists(new_filename) else None
        os.rename(downloaded_file, new_filename)
        downloaded_file = self.download_folder+"/range-production.csv"
        log(f"{Colors.GREEN}File downloaded and saved as: {new_filename} {round(os.path.getsize(downloaded_file)/1024,2)} KB{Colors.RESET}")
    else:
        log(f"{Colors.RED}No file was downloaded.{Colors.RESET}")
    log("All Done - INTERVAL DATA DOWNLOADED")
    data_consumption = pd.read_csv(self.download_folder + '/range-consumption.csv', delimiter=';', encoding='latin1', converters={0: lambda s: dt.strptime(s.replace("24:00:00","23:59:00"), "%d.%m.%Y %H:%M:%S")})
    data_production = pd.read_csv(self.download_folder + '/range-production.csv', delimiter=';', encoding='latin1', converters={0: lambda s: dt.strptime(s.replace("24:00:00","23:59:00"), "%d.%m.%Y %H:%M:%S")})

    date_str = [_dt.date().isoformat() for _dt in data_consumption.iloc[:, 0]]

    consumption_str = data_consumption.iloc[:, 1].to_list()
    production_str = data_production.iloc[:, 1].to_list()

    now = dt.now()
    self.set_state(f"sensor.pnd_data{self.suffix}", state=now.strftime("%Y-%m-%d %H:%M:%S"), attributes={"pnddate": date_str, "consumption": consumption_str, "production": production_str})
    total_consumption = "{:.2f}".format(data_consumption.iloc[:, 1].sum())
    total_production = "{:.2f}".format(data_production.iloc[:, 1].sum())
    self.set_state(f"sensor.pnd_total_interval_consumption{self.suffix}", state=total_consumption,attributes={
      "friendly_name": "PND Total Interval Consumption",
      "device_class": "energy",
      "unit_of_measurement": "kWh"
    })
    self.set_state(f"sensor.pnd_total_interval_production{self.suffix}", state=total_production,attributes={
      "friendly_name": "PND Total Interval Production",
      "device_class": "energy",
      "unit_of_measurement": "kWh"
    })
    try:
        percentage_diff = round((float(total_production) / float(total_consumption)) * 100, 2)
    except:
        percentage_diff = 0
    capped_percentage_diff = round(min(percentage_diff, 100),2)
    floored_min_percentage_diff = round(max(percentage_diff - 100, 0),2)
    self.set_state(f"sensor.pnd_production2consumption{self.suffix}", state=capped_percentage_diff,attributes={
      "friendly_name": "PND Interval Production to Consumption Max",
      "device_class": "energy",
      "unit_of_measurement": "%"
    })
    self.set_state(f"sensor.pnd_production2consumptionfull{self.suffix}", state=percentage_diff,attributes={
      "friendly_name": "PND Interval Production to Consumption Full",
      "device_class": "energy",
      "unit_of_measurement": "%"
    })
    self.set_state(f"sensor.pnd_production2consumptionfloor{self.suffix}", state=floored_min_percentage_diff,attributes={
      "friendly_name": "PND Interval Production to Consumption Floor",
      "device_class": "energy",
      "unit_of_measurement": "%"
    })
    #----------------------------------------------
    log("All Done - INTERVAL DATA PROCESSED")


    # Close the browser
    quit_driver(driver)
    log("All Done - BROWSER CLOSED")
    self.set_state(f"binary_sensor.pnd_running{self.suffix}", state="off")
    log("Sensor State Set to OFF")
    zip_folder(f"/homeassistant/appdaemon/apps/pnd{self.suffix}", f"/homeassistant/appdaemon/apps/debug{self.suffix}.zip")
    shutil.move(f"/homeassistant/appdaemon/apps/debug{self.suffix}.zip", self.download_folder+"/debug.zip")
    log("Debug Files Zipped")
    script_end_time = dt.now()
    script_duration = script_end_time - script_start_time
    self.set_state(f"sensor.pnd_script_duration{self.suffix}", state=script_duration,attributes={
      "friendly_name": "PND Script Duration",
    })
    self.set_state(f"sensor.pnd_script_status{self.suffix}", state="Stopped",attributes={
      "status": "Finished",
    })
    log(f"{Colors.CYAN}********************* Duration: {script_duration} *********************{Colors.RESET}")
    log(f"{Colors.CYAN}********************* Finished {ver} *********************{Colors.RESET}")
