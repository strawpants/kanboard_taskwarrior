#!/usr/bin/env python
# Author R.Rietbroek, Aug 2022

import sys
import os
from kanboard_taskwarrior.db import DbConnector

# import sqlite3
import argparse
import logging
from pprint import pprint
import time









def main(argv):

    #parse command line arguments

    usage=" Program to synchronize kanboard and taskwarrrior tasks"
    parser = argparse.ArgumentParser(description=usage)
    
    parser.add_argument('project',metavar="Project",type=str,nargs="?",
            help="Specify specific project to apply the actions to (default takes all)")

    parser.add_argument('-c','--config',action='store_true',
                        help="Configure/modify kanboard-taskwarrior connections")

    parser.add_argument('-s','--sync',action='store_true',
                        help="Synchronize the registered connections")

    
    parser.add_argument('-d','--daemonize',action='store',nargs="?",metavar="SECONDS",type=int,const=180,help="Run the syncing operation as a service (default checks once every 180 seconds)")
    
    parser.add_argument('-t','--test',action='store_true',
                        help="Report the actions which a sync would do but do not actually execute them")

    
    parser.add_argument('-l','--list',action='store_true',
                        help="List configured couplings")
    parser.add_argument('-v','--verbose',action='count',default=0,help="Increase verbosity (more -v's mean an increased verbosity)")    
    if len(argv) == 1:
        print("No command line arguments provided")
        parser.print_help()
        sys.exit(0)

    args=parser.parse_args(argv[1:]) 
    if args.verbose == 1:
        loglevel=logging.INFO
    elif args.verbose > 1:
        loglevel=logging.DEBUG
    else:
        loglevel=logging.WARNING
    logging.basicConfig(format='tasksync-%(levelname)s:%(message)s', level=loglevel)

    #open up a connection with a database 
    conn=DbConnector()

    if args.list:
        for projname,res in conn.items():
            print(f"Project: {projname} found at {res['url']}\n registered mapping:")
            #also print mapping
            pprint(res["mapping"])
        sys.exit(0)

    if args.config:
        if not args.project:
            logging.error("Configuring a project requires a project name")
            sys.exit(1)
        conn.config(args.project)

    if args.sync:
        if args.daemonize:
            while True:
                conn.syncTasks(args.project,args.test)
                logging.info(f"Sleeping for {args.daemonize} seconds")
                time.sleep(args.daemonize)
        else:
            conn.syncTasks(args.project,args.test)


if __name__ == "__main__":
    main(sys.argv)
