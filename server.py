#!/usr/bin/env python

import threading
from pqueue import Queue
import sys
import os
from datetime import datetime

import argparse

from bottle import run, post, request, response, get, route

from database_manager import DatabaseManager
from s3_util import FileManager
import logging

import originality
import concordance

PORT = os.environ.get("PORT", "5151")
API_KEY = os.environ.get("API_KEY", "h/52y/E7cm8Ih4F3cVdlBM4ZQxER+Apk6P0L7yR0lFU=")
TEMP_DIR, OQ_DIR, CQ_DIR = "queue_temp", "oqueue", "cqueue"
LB_TEMP_DIR, LBQ_DIR = "lb_temp", "lbqueue"

for d in [TEMP_DIR, OQ_DIR, CQ_DIR, LB_TEMP_DIR, LBQ_DIR]:
    if not os.path.exists(d):
        os.makedirs(d)

originality_queue = Queue(OQ_DIR, tempdir=TEMP_DIR)
concordance_queue = Queue(CQ_DIR, tempdir=TEMP_DIR)
leaderboard_queue = Queue(LBQ_DIR, tempdir=LB_TEMP_DIR)

"""
To use this, do something like

requests.post("http://localhost:5151/", data={'user': 'zuz', 'submission_id': '58d411e57278611200ee49a6', 'competition_id': 41})
"""
@route('/', method='POST')
def queue_for_scoring():
    json = request.json
    submission_id = json["submission_id"]
    api_key = json["api_key"]

    if API_KEY is None:
        logging.getLogger().critical("NO API KEY EXITING")
        return
    if api_key != API_KEY:
        logging.getLogger().info("Received invalid post request with api_key {} and submission_id {}".format(api_key, submission_id))
        return

    logging.getLogger().info("Received request to score {}".format(submission_id))

    data = {
        'submission_id':submission_id,
        'enqueue_time':datetime.now(),
    }

    leaderboard_queue.put(data)

def put_submission_on_lb(db_manager, filemanager):
    # Makes sure a new submission is put on the LB, and then fires off concordance and originality checks.
    while True:
        submission = leaderboard_queue.get()
        try:
            db_manager.update_leaderboard(submission["submission_id"], filemanager)

            for queue in [originality_queue, concordance_queue]:
                queue.put(submission)

            leaderboard_queue.task_done()
        except Exception as e:
            logging.exception("Exception putting submission on the LB.")

def score_concordance(db_manager, filemanager):
    while True:
        submission = concordance_queue.get()
        try:
            concordance.submission_concordance(submission, db_manager, filemanager)
            if 'enqueue_time' in submission:
                time_taken = datetime.now() - submission['enqueue_time']
                logging.getLogger().info("Submission {} took {} to complete concordance".format(submission['submission_id'], time_taken))

            concordance_queue.task_done()
        except Exception as e:
            logging.exception("Exception scoring concordance.")

def score_originality(db_manager, filemanager):
    while True:
        submission_data = originality_queue.get()
        try:
            originality.submission_originality(submission_data, db_manager, filemanager)
            if 'enqueue_time' in submission_data:
                time_taken = datetime.now() - submission_data['enqueue_time']
                logging.getLogger().info("Submission {} took {} to complete originality".format(submission_data['submission_id'], time_taken))

            originality_queue.task_done()

        except Exception as e:
            logging.exception("Exception scoring originality.")

def create_logger():
    """Configure the logger to print process ID."""
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(process)d - {} - %(message)s'.format("Machine learning Server"))
    ch.setFormatter(formatter)
    root.addHandler(ch)

if __name__ == '__main__':
    """
    The threading in this file works like this

    We have a bottle server listening for submissions. When it gets a submission
    it gives it to the put_submission_on_lb. This makes sure that the user is on the
    leaderboard/ the leaderboard reflects their most up to date submission.

    That method then enqueues the submission for concordance and originality checks.
    """

    parser = argparse.ArgumentParser(description="Score if submissions are original.")
    parser.add_argument("--use_local", dest = "local" ,action="store_true", help="Use the local database")
    parser.add_argument("--num_threads", dest = "num_threads", type=int, default=32, help="Number of threads to use.")
    parser.set_defaults(local=False)
    args = parser.parse_args()

    create_logger()
    db_manager = DatabaseManager(local_db = args.local)
    fm = FileManager('/tmp/', logging)
    logging.getLogger().info("Creating servers")


    threading.Thread(target=run, kwargs=dict(host='0.0.0.0', port=int(PORT))).start()
    logging.getLogger().info("Spawning new threads to score originality and concordance")

    threading.Thread(target=put_submission_on_lb, kwargs=dict(db_manager=db_manager, filemanager=fm)).start()
    for _ in range(args.num_threads - 3):
        threading.Thread(target=score_originality, kwargs=dict(db_manager=db_manager, filemanager=fm)).start()
    threading.Thread(target=score_concordance, kwargs=dict(db_manager=db_manager, filemanager=fm)).start()
