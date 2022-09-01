# Author R. Rietbroek Aug 2022
# contains functionality to connect to kanboard servers and local taskwarrior instances

import kanboard
import requests
import logging
from tasklib import TaskWarrior,Task

def serverIsreachable(server="example.com",timeout=2):
    try:
        requests.head(server, timeout=timeout)
        return True
    except requests.ConnectionError:
        logging.warning(f"Kanboard server {server} is not reachable, skipping")
        return False

def kbClient(kbserver,user,apitoken):
    if not serverIsreachable(kbserver):
        return None
    return kanboard.Client(kbserver,user,apitoken)


TWDoesNotExist=Task.DoesNotExist
KBClientError=kanboard.ClientError

def twClient():
    return TaskWarrior(create=False)
