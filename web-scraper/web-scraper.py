#!/usr/bin/env python
from flickrapi import FlickrAPI
import googlemaps

import multiprocessing
from multiprocessing import pool
from functools import partial

import config
from db_utils import DBUtils

import logging

'''
Library to scrape images from Flickr based on search text list in parallel

Run:
1. Activate virtualenv which has the needed libraries that are used.
    Mac/Linux: scraper/bin/activate
2. python web-scraper.py
3. Check results:
     sqlite3 scraper.db
     select * from image_metadata;
Author: Shruti Rachh
'''

class WebScraper:
    '''
    This class provides functionality to scrape images with multiple searches all executing in parallel.
    It uses Flickr API to get the images information and Google Maps API to handle missing geo data.
    '''

    def __init__(self, search_text_list, photos_per_page, extras):
        '''
        Constructor to initialize the parameters needed by Flickr API to retrieve the images in parallel
        :param search_text_list: list of searches to be made
        :param photos_per_page: number of photos to be retrieved at a time (MAX=500), a limit set by Flickr API
        :param extras: comma-separated string denoting extra information to be retrieved for the photos, used here to get geo information
        '''
        self.search_text_list = search_text_list
        if photos_per_page > 500:
            self.photos_per_page = 500
        else:
            self.photos_per_page = photos_per_page
        self.extras = extras
        self.flickr = FlickrAPI(config.FLICKR_PUBLIC, config.FLICKR_SECRET, format='parsed-json')

        self.no_of_processors = multiprocessing.cpu_count()
        self.logger = multiprocessing.get_logger()
        self.logger.setLevel(logging.INFO)

        # Google Maps API is used to get the missing geo info in images
        self.maps = googlemaps.Client(key=config.GOOGLE_API_KEY)
        self.dbutils = DBUtils()

    @property
    def search_text_prop(self):
        '''
        Gets the search text list
        :return: search text list
        '''
        return self.search_text_list

    @search_text_prop.setter
    def search_text_prop(self, search_text):
        '''
        Adds to the search text list
        :param search_text: text to be searched
        '''
        self.search_text_list.append(search_text)

    @property
    def photos_per_page_prop(self):
        '''
        Gets the photos per page property
        :return: number of photos retrieved at a time
        '''
        return self.photos_per_page

    @photos_per_page_prop.setter
    def photos_per_page_prop(self, photos_per_page):
        '''
        Sets the photos per page property
        :param photos_per_page: number of photos to be retrieved at a time (MAX=500), limit set by Flickr API
        '''
        self.photos_per_page = photos_per_page

    @property
    def extras_prop(self):
        '''
        Gets the extras property
        :return: comma-separated string denoting extra information to be retrieved for the photos
        '''
        return self.extras

    @extras_prop.setter
    def extras_prop(self, extras):
        '''
        Set the extras property
        :param extras: comma-separated string denoting extra information to be retrieved for the photos
        '''
        self.extras = extras

    @property
    def no_of_processors_prop(self):
        '''
        Gets the number of processors running on a machine
        :return: number of processors
        '''
        return self.no_of_processors

    @property
    def logger_object(self):
        '''
        Gets logger object for multiprocessing and logs info, debug, error messages
        :return: logger object
        '''
        return self.logger

    @property
    def db_utils_object(self):
        '''
        Gets the DBUtils object used for database operations
        :return: DBUtils object
        '''
        return self.dbutils

    def get_missing_geo_data(self, search_text):
        '''
        Gets the missing geo data using Google Maps API based on generic search text.
        Saves this data in database for future use.
        :param search_text: text that was searched, assuming it is a place.
        :return: a tuple (search_text,latitude,longitude)
        '''
        result = self.dbutils.get_data(config.default_geo_info_table, 'search_text', search_text)
        if result:
            return result[0]
        else:
            matches = self.maps.geocode(search_text)
            if matches:
                geo_info = matches[0]['geometry']['location']
                params = (search_text, str(geo_info['lat']), str(geo_info['lng']))
                self.dbutils.insert_data(config.default_geo_info_table, params)
                return params
        return ()

    def insert_image_metadata_db(self, photo, search_text):
        '''
        Inserts image metadata such as id, filename and geo information into the sqlite database, if not already inserted.
        :param photo: image data
        :param search_text: text that was searched used for the purpose of handling missing geo information
        '''
        result = self.dbutils.get_data(config.image_metadata_table, 'id', photo['id'])
        if not result:
            if str(photo['latitude']) == '0' or str(photo['longitude']) == '0':
                geo_data = self.get_missing_geo_data(search_text)
                if geo_data:
                    photo['latitude'] = geo_data[1]
                    photo['longitude'] = geo_data[2]
            params = (str(photo['id']), str(photo['title']), str(photo['latitude']), str(photo['longitude']))
            self.dbutils.insert_data(config.image_metadata_table, params)

    def get_no_of_pages(self, search_text):
        '''
        Gets the number of pages for the given search text depending on the number of photos that are retrieved per page.
        :param search_text: text to be searched
        :return: number of pages
        '''
        return self.flickr.photos.search(text=search_text, per_page=self.photos_per_page, extras=self.extras)['photos']['pages']

    def get_pages(self, search_text):
        '''
        Gets the pages for the given search text and processes the images in parallel
        :param search_text: text to be searched
        '''
        self.logger.info('Fetching photos for ' + search_text)
        no_of_pages = self.get_no_of_pages(search_text)
        for page_no in range(1, no_of_pages):
            photos = self.flickr.photos.search(text=search_text, per_page=self.photos_per_page, extras=self.extras,
                                               page=page_no)['photos']['photo']
            sub_process_pool = NoDaemonProcessPool(self.no_of_processors)
            sub_process_pool.map(partial(self.insert_image_metadata_db, search_text=search_text), photos)
            sub_process_pool.close()
            sub_process_pool.join()

class NoDaemonProcess(multiprocessing.Process):
    '''
    This class is used to set daemon property to false for a process which will allow to create sub processes.
    By default, multiprocessing pool creates a daemon process and it cannot be overridden.
    '''

    def _get_daemon(self):
        return False

    def _set_daemon(self, value):
        pass
    daemon = property(_get_daemon, _set_daemon)

class NoDaemonProcessPool(multiprocessing.pool.Pool):
    '''
    This class creates no daemon process that allows for creation of sub processes
    '''
    Process = NoDaemonProcess


if __name__ == '__main__':
    search_list = ['paris', 'rome', 'new york']
    scraper = WebScraper(search_list, 500, 'geo')
    scraper.logger_object.info('Creating needed database tables')
    scraper.dbutils.create_db_tables()

    # Creates a pool of no daemon processes to allow for parallel searches of images and in turn creates sub processes
    # to get the images metadata in parallel
    scraper.logger_object.info('Assigning jobs to available processors..')
    pool = NoDaemonProcessPool(scraper.no_of_processors_prop)
    pool.map(scraper.get_pages, scraper.search_text_prop)
    pool.close()
    pool.join()