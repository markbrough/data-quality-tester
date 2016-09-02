#!/usr/bin/env python
import os.path
import unicodecsv

from flask import Flask, flash, render_template, redirect, request, url_for
from foxpath import test as foxtest
from lxml import etree
import requests
from werkzeug.contrib.cache import SimpleCache  # MemcachedCache

import codelists
from pagination import Pagination


app = Flask(__name__)
app.secret_key = "super top secret key"
CACHE_TIMEOUT = 86400  # 24 hours

cache = SimpleCache()
# cache = MemcachedCache(['127.0.0.1:11211'])

LISTS = codelists.CODELISTS
TESTS_FILE = 'tests.csv'
FILTERS_FILE = 'filters.csv'
UPLOAD_FOLDER = 'uploads'
REGISTRY_API_BASE_URL = "https://iatiregistry.org/api/3/action"
PER_PAGE = 20

def exec_request(url, refresh=False, *args, **kwargs):
    if not refresh:
        response = cache.get(url)
        if response:
            # cache hit
            return response
    response = requests.get(url, *args, **kwargs)
    cache.set(url, response, CACHE_TIMEOUT)
    return response

def download_package(url, filepath):
    # download if we don't have a cached copy
    if not os.path.exists(filepath):
        r = requests.get(url, stream=True)
        with open(filepath, 'w') as f:
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:
                    f.write(chunk)

def fetch_latest_package_version(package_name, refresh=False):
    registry_url = "{registry_api}/package_show?id={package_name}".format(
        registry_api=REGISTRY_API_BASE_URL,
        package_name=package_name
    )
    j = exec_request(registry_url, refresh=refresh).json()
    resource = j["result"]["resources"][0]
    url = resource["url"]
    revision = resource["revision_id"]
    filename = "{package_name}-{revision}.xml".format(
        package_name=package_name,
        revision=revision
    )
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    return url, revision, filepath

def load_expressions_from_file(filename):
    out = []
    with open(filename) as f:
        reader = unicodecsv.DictReader(f)
        for t in reader:
            out.append({
                'name': t["test_description"],
                'fn': foxtest.generate_function(t["test_name"]),
                'is_binary': foxtest.binary_test(t["test_name"]),
            })
    return out

def test_package(filepath):
    # load the tests
    all_tests = [t for t in load_expressions_from_file(TESTS_FILE)]
    all_filters = [t for t in load_expressions_from_file(FILTERS_FILE)]

    results = []
    doc = etree.parse(filepath)
    activities = doc.xpath("//iati-activity")
    for activity in activities:
        act_test = {}
        try:
            act_test["hierarchy"] = activity.xpath("@hierarchy")[0]
        except Exception:
            act_test["hierarchy"] = ""
        try:
            act_test["iati_identifier"] = activity.xpath('iati-identifier/text()')[0]
        except Exception:
            act_test["iati_identifier"] = "Unknown"
        act_test["results"] = {}
        for test_dict in all_tests:
            try:
                if test_dict["is_binary"]:
                    result = test_dict["fn"]({"activity": activity, "lists": LISTS})
                else:
                    result = test_dict["fn"](activity)
            except Exception:
                result = 2
            act_test["results"][test_dict["name"]] = foxtest.result_t(result)
        results.append(act_test)

    return results

def fetch_activity(filepath, iati_identifier):
    doc = etree.parse(filepath)
    activities = doc.xpath("//iati-identifier[text() = '" + iati_identifier + "']/..")
    return etree.tostring(activities[0])

def url_for_other_page(page):
    args = request.view_args.copy()
    args['page'] = page
    return url_for(request.endpoint, **args)
app.jinja_env.globals['url_for_other_page'] = url_for_other_page

@app.route('/')
def home():
    publishers = []
    j = exec_request("{registry_api}/organization_list?all_fields=true".format(
        registry_api=REGISTRY_API_BASE_URL,
    )).json()

    page = int(request.args.get('page', 1))
    offset = (page - 1) * PER_PAGE
    results = j["result"][offset:offset + PER_PAGE]

    pagination = Pagination(page, PER_PAGE, len(j["result"]))

    for publisher in results:
        publishers.append({
            "code": publisher["name"],
            "name": publisher["title"],
            "num_packages": publisher["packages"],
        })

    kwargs = {
        "pagination": pagination,
        "publishers": publishers,
    }
    return render_template('publishers.html', **kwargs)

@app.route('/publisher/<publisher>')
def publisher(publisher):
    resources = []
    registry_tmpl = "{registry_api}/package_search?q=organization:{{publisher}}&rows={per_page}&start={{offset}}".format(
        registry_api=REGISTRY_API_BASE_URL,
        per_page=PER_PAGE,
    )
    page = int(request.args.get('page', 1))
    offset = (page - 1) * PER_PAGE

    j = exec_request(registry_tmpl.format(publisher=publisher, offset=offset)).json()
    pagination = Pagination(page, PER_PAGE, j["result"]["count"])
    for result in j["result"]["results"]:
        filetype = [extra["value"] for extra in result["extras"] if extra["key"] == "filetype"][0]
        for resource in result["resources"]:
            resources.append({
                "title": result["title"],
                "url": resource["url"],
                "package_name": result["name"],
                "revision": resource["revision_id"],
                "filetype": filetype,
            })
    kwargs = {
        "resources": resources,
        "publisher": publisher,
        "pagination": pagination,
    }
    return render_template('publisher.html', **kwargs)

@app.route('/test/<package_name>')
def run_tests(package_name):
    refresh = request.args.get("refresh", False)
    url, revision, filepath = fetch_latest_package_version(package_name, refresh)
    download_package(url, filepath)

    activities = test_package(filepath)
    args = {
        "package_name": package_name,
        "revision": revision,
        "activities": activities,
    }
    return render_template('results.html', **args)

@app.route('/activity/<package_name>/<iati_identifier>')
def view_activity(package_name, iati_identifier):
    refresh = request.args.get("refresh", False)
    url, revision, filepath = fetch_latest_package_version(package_name, refresh)
    download_package(url, filepath)

    activity = fetch_activity(filepath, iati_identifier).strip()
    kwargs = {
        "package_name": package_name,
        "activity": activity,
    }
    return render_template('activity.html', **kwargs)