#!/usr/bin/env python

import datetime
import decimal
import io
import json
import os
import re
import sys
import time

import pytz
import utcdatetime

import lxml.html
from collections import namedtuple

from selenium import webdriver
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By


Snipe = namedtuple('Snipe', 'item_number,end_datetime,amount')


class EbayScraper():
    HOME = 'https://www.ebay.co.uk'
    MY_EBAY = 'https://www.ebay.co.uk/myb/Summary'
    WATCH_LIST = 'https://www.ebay.co.uk/myb/WatchList#WatchListContainer?ipp=100'
    ITEM_LISTING = 'https://www.ebay.co.uk/itm/{}'

    def __init__(self, webdriver):
        self.d = webdriver

        if self.attempt_restore_login():
            pass
        else:
            self.login()

    def attempt_restore_login(self):
        self.d.get(self.HOME)
        try:
            with io.open('cookies.json', 'r') as f:
                cookies = json.load(f)
        except FileNotFoundError:
            return False

        for cookie in cookies:
            self.d.add_cookie(cookie)

        self.d.get(self.MY_EBAY)
        return 'Sign in' not in self.d.title

    def login(self):
        USERNAME = os.environ['EBAY_USERNAME']
        PASSWORD = os.environ['EBAY_PASSWORD']

        self.d.get(self.MY_EBAY)
        username_input = self.d.find_element_by_id("userid")
        username_input.send_keys(USERNAME)

        password_input = self.d.find_element_by_id("pass")
        password_input.send_keys(PASSWORD)

        sign_in_button = self.d.find_element_by_id("sgnBt")
        sign_in_button.click()

        with io.open('cookies.json', 'w') as f:
            json.dump(self.d.get_cookies(), f, indent=4)

    def get_snipes(self):
        """
        Look through the watched items list and extract notes of the format
        `snipe: 45` to snipe for £45.00
        """
        self.d.get(self.WATCH_LIST)

        parser = WatchListSnipesParser(self.d.page_source)
        snipes = []

        for item_number, amount in parser.get_snipes():
            end_datetime = self.get_end_datetime(item_number)

            snipes.append(
                Snipe(
                    item_number=item_number,
                    end_datetime=end_datetime,
                    amount=amount
                )
            )
        return snipes

    def snipe(self, snipe):

        self.d.get(self.ITEM_LISTING.format(snipe.item_number))

        bid_input = self.d.find_element_by_id('MaxBidId')
        submit_button = self.d.find_element_by_id('bidBtn_btn')

        bid_input.send_keys(str(snipe.amount))
        submit_button.click()

        wait = WebDriverWait(self.d, 10)

        while True:
            confirm_button = wait.until(
                EC.element_to_be_clickable((By.ID, 'confirm_button'))
            )

            remaining_seconds = (
                snipe.end_datetime - utcdatetime.utcdatetime.now()
            ).total_seconds()

            if remaining_seconds <= 5:
                print('Clicking confirm_button: {}'.format(confirm_button))
                confirm_button.click()
                break
            else:
                print('Clicking in {} seconds'.format(remaining_seconds))

            time.sleep(1)

    def get_end_datetime(self, item_number):
        self.d.get(self.ITEM_LISTING.format(item_number))

        end_dt = self.d.find_element_by_xpath(
            "//span[contains(@class, 'vi-tm-left')]"
        )
        return parse_datetime(end_dt.text)


class WatchListSnipesParser():
    def __init__(self, page_source):
        # with io.open('watch_list.html', 'w') as f:
        #     f.write(page_source)

        self.root = lxml.html.fromstring(page_source)

    def get_snipes(self):

        item_specs = self.root.xpath("//div[contains(@class, 'item-spec')]")

        for item_spec in item_specs:
            snipe_notes = item_spec.xpath(
                ".//div[contains(text(), 'snipe')]"
            )
            item_number = item_spec.xpath(
                ".//div[contains(@class, 'display-item-id')]"
            )

            if len(snipe_notes):
                note = snipe_notes[0].text_content().strip()
                item_num = item_number[0].text_content().strip(' ()')
                pounds = self._parse_snipe_note(note)

                yield item_num, pounds

    @staticmethod
    def _parse_snipe_note(note):
        """
        snipe: 45
        snipe: 45.00
        snipe: £45.00
        """

        match = re.match('snipe: £?(?P<amount>[0-9.]+)', note)

        if match:
            return decimal.Decimal(
                '{:.2f}'.format(float(match.group('amount')))
            )


def parse_datetime(string):
    """
    (11 Jul, 2018
    09:58:34 BST)
    """

    string = re.sub('\s+', ' ', string.strip(' ()'))
    london = pytz.timezone('Europe/London')
    utcdt = utcdatetime.utcdatetime.from_datetime(
        london.localize(datetime.datetime.strptime(string, '%d %b, %Y %H:%M:%S %Z'))
    )
    return utcdt


class Sniper():
    def __init__(self, ebay, pause_func):
        self._ebay = ebay
        self.pause = pause_func

        self._snipes = []
        self._next_check = None

    def run(self):
        self.update_snipes()

        while True:
            next_snipe = self.next_snipe()
            if next_snipe:
                time_to_next = self.time_to(next_snipe.end_datetime)
                print('Next snipe in {}: {}'.format(time_to_next, next_snipe))

                if time_to_next < datetime.timedelta(minutes=1):
                    self._ebay.snipe(next_snipe)

            else:
                print('No upcoming snipes')

            if self.due_recheck_snipes():
                self.update_snipes()

            print("Nothing to do, sleeping for 30s")
            self.pause(30)

    def now(self):
        return utcdatetime.utcdatetime.now()

    def due_recheck_snipes(self):
        return not self._next_check or self.now() >= self._next_check

    def update_snipes(self):
        print('Updating list of snipes')
        self._snipes = self._ebay.get_snipes()
        self._next_check = self.now() + datetime.timedelta(minutes=5)
        print('{} snipes: {}'.format(len(self._snipes), self._snipes))

    def next_snipe(self):
        earliest = None

        for snipe in self._snipes:
            if not earliest or snipe.end_datetime < earliest.end_datetime:
                earliest = snipe

        return earliest

    @staticmethod
    def time_to(dt, now=None):
        now = now or utcdatetime.utcdatetime.now()
        return dt - now


def main(argv):

    try:
        driver = webdriver.Firefox()
        ebay = EbayScraper(driver)

        def pause(seconds):
            for i in range(seconds):
                time.sleep(1)
                driver.get_cookies()

        sniper = Sniper(ebay, pause)
        sniper.run()
    finally:
        driver.close()


if __name__ == '__main__':
    main(sys.argv)
