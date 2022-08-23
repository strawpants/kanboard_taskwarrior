#!/usr/bin/env python
# Author R.Rietbroek, Aug 2022

import sys
import os
import sqlite3
from contextlib import closing
import kanboard
from tasklib import TaskWarrior,Task 
import argparse
import logging
from collections import OrderedDict
import json
from pprint import pprint
from datetime import datetime,timedelta,date
import time
import requests

serverTable="kbserver"


def isKanboardConnected(server,timeout=1):
    
    try:
        requests.head(server, timeout=timeout)
        return True
    except requests.ConnectionError:
        logging.warning(f"Kanboard server {server} is not reachable, skipping")
        return False

def newcur(conn):
    return closing(conn.cursor())


def tableExists(conn,tablename):
    tExists=False
    with newcur(conn) as cur:
        cur.execute(f"""
        SELECT COUNT(*)
        FROM sqlite_master
        WHERE type = 'table'  AND name = '{tablename}'
        """)
        
        if cur.fetchone()[0] == 1:
            tExists=True
        
    return tExists

def openDb():
    dbfile=os.path.join(os.path.expanduser('~'),".task/taskw-sync-KB.sql")
    try:
        conn=sqlite3.connect(dbfile,detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
        conn.row_factory = sqlite3.Row
    except Error as e:
        print(e)
        if conn:
            conn.close()
    return conn

def getKanboardSync(conn,project=None):
    if not tableExists(conn,serverTable):
        with newcur(conn) as cur:
            cur.execute(f"""
            CREATE TABLE {serverTable} (url TEXT, apitoken TEXT, user TEXT, project TEXT UNIQUE, projid INT,  mapping json, lastsync TIMESTAMP,PRIMARY KEY(project))
            """)

    with newcur(conn) as cur:
        if project:
            res=cur.execute(f"SELECT * from {serverTable} WHERE project = '{project}';").fetchone()
        else:
            res=cur.execute(f"SELECT * from {serverTable}").fetchall()

    
    if res == None:
        #return an empty directory so keys can be tested on the result
        return {}
    

    return res




def prompt(message,default=""):
    if default != "":
        mssg=message+f" [{default}]: "
    else:
        mssg=message+": "
    inp=input(mssg)
    if inp:
        tp=type(default)
        return tp(inp)
    elif default != "":
        return default
    else:
        raise ValueError("Invalid input")

def getDefault(projconf,key):
    if key in projconf.keys():
        return projconf[key]
    else:
        return ""

def getMapper(projconf):
    if "mapping" in projconf.keys():
        mapper=json.loads(projconf["mapping"])
    else:
        mapper={}

    return mapper

def configUDA(mapper):
    tpy="string"

    tw=TaskWarrior(create=False)
    for udaky,udamap in mapper.items():
        if not udaky.startswith("uda"):
            continue

        udaval=[ky for ky in udamap.keys()] 
        # #retrieve an existing uda (to update values)
        valky=f"{udaky}.values"
        labky=f"{udaky}.label"
        typeky=f"{udaky}.type"

        # if valky in tw.config:
            # udaval2=tw.config[valky]
        if udaky == "uda.swimlane":
            label="kbSwim"
        elif udaky == "uda.kbcat":
            label="kbCat"
        else:
            label="kb"

        #set label, type and permissible values
        tw.execute_command(["config", typeky, tpy])

        tw.execute_command(["config", labky,label])

        tw.execute_command(["config",valky,','.join(udaval)])


def configKanboardSync(conn,project):
    """Setup or modify a Kanboard-Taskwarrior synchronization"""

    if not project:
        raise RuntimeError("Configuration of a connection requires specifying a project name")
    
    #try to get existing confiuguration data
    projconf=getKanboardSync(conn,project)
    if not projconf:
        create=prompt(f"Project mapping {project} does not exist yet, create a new mapping (y/n)?","y").lower() == "y"
        if not create:
            logging.info("Not creating a new project mapping, quitting")
            sys.exit(0)
    
    logging.info("Setting up Kanboard- taskwarrior mapping")
    
    #query user interactively for settings
    kbserver=prompt("Enter Kanboard serveraddress",getDefault(projconf,'url'))
    if not kbserver.endswith('/jsonrpc.php'):
        kbserver+="/jsonrpc.php"
    if not kbserver.startswith('http'):
        kbserver="https://"+kbserver

    user=prompt("Enter your Kanboard username",getDefault(projconf,'user'))
    apitoken=prompt("Enter personal Kanboard API Token (create in Kanboard under My profile -> API): ",getDefault(projconf,'apitoken'))

    #perform a quick intermediate save on the authentication data so users 

    if not isKanboardConnected(kbserver):
        return
    kb=kanboard.Client(kbserver,user,apitoken)
    try:
        proj=kb.getProjectByName(name=project)
    except kanboard.ClientError:
        logging.error(f"Can not find kanboard project named {project}. Does it exist?")
        sys.exit(1)
    with newcur(conn) as cur:
        if not projconf:
            cur.execute(f"INSERT INTO {serverTable} (url,user,apitoken,project,projid,lastsync) VALUES ('{kbserver}','{user}','{apitoken}','{project}',{proj['id']},datetime('2000-01-01'))")
        else:
            cur.execute(f"UPDATE {serverTable} SET url = '{kbserver}',user = '{user}', apitoken = '{apitoken}',project = '{project}',projid = {proj['id']},lastsync = datetime('2000-01-01') WHERE project = '{project}'")
    
    conn.commit()
    mapper=getMapper(projconf)
    mapper={}
    colkey="vtag.columns"
    catkey="uda.kbcat"
    swimkey="uda.swimlane"
    
    if not mapper:
        mapper={colkey:{},swimkey:{},catkey:{}}

    # Set up the column mapping
    columns=[{"kbid":el["id"],"name":el["title"]} for el in kb.getColumns(project_id=proj["id"])]
    


#a list of supported taskwarrior vtags which are associated with dates and can be assigned to the columns
    vtags=OrderedDict()

    vtags[0]="WAITING"
    vtags[1]="ACTIVE"
    vtags[2]="WEEK"
    vtags[3]="TOMORROW"
    vtags[4]="COMPLETED"
    
    for col in columns:
        
        defaultvtag=next(iter([ky for ky,val in mapper[colkey].items() if val["name"] == col["name"]]),next(iter(vtags.items()))[1])

        default=[j for j,vt in vtags.items() if vt == defaultvtag][0]

        vtagdescr=", ".join([f"{i}:{val}" for i,val in vtags.items()])
        kbcol=prompt(f"Select taskwarrior virtual tag to map to Kanboard column '{col['name']}'\n {vtagdescr}",default)
        
        mapper["vtag.columns"][vtags[kbcol]]=col  
        del vtags[kbcol]


    # Map kanboard swimlanes to a Taskwarrior custom UDA: swimlane, with fixed values
    swimlanes=kb.getActiveSwimlanes(project_id=proj["id"])
    twswimlanealias=[]
    for el in swimlanes:
        default=next(iter([ky for ky,val in mapper[swimkey].items() if val["kbid"] == el["id"]]),el["name"])
        twswimlanealias.append(prompt(f"Select Taskwarrior alias for Kanboard swimlane {el['name']}",default))
    mapper[swimkey]={twswim:{"kbid":el["id"],"name":el["name"]} for twswim,el in zip(twswimlanealias,swimlanes)}

            


    # map categories to taskwarrior UDA's 
    categories=kb.getAllCategories(project_id=proj["id"])
    twcatalias=[]
    for el in categories:
        default=next(iter([ky for ky,val in mapper[catkey].items() if val["kbid"] == el["id"]]),el["name"])
        twcatalias.append(prompt(f"Select Taskwarrior alias for Kanboard category {el['name']}",default))
    

    mapper[catkey]={twcat:{"kbid":el["id"],"name":el["name"]} for twcat,el in zip(twcatalias,categories)}


    #update the mapping in the database (convert to json on the fly)
    with newcur(conn) as cur:
        # cur.execute(f"UPDATE {serverTable} SET mapping = '{json.dumps(mapper)}' WHERE project = '{project}'")
        cur.execute(f"UPDATE {serverTable} SET mapping = (?) WHERE project = '{project}'",(json.dumps(mapper),))
    
    conn.commit()


    #now setup taskwarrior  UDA's
    configUDA(mapper) 

def twFromkbTask(kbtask,twclient,mapper,projconf,twtask=None,test=False):
    #
    if twtask is None:
        #create a new taskwarrior task
        twtask=Task(twclient,description=kbtask['title'])
    else:
        #update an existing one
        twtask['description']=kbtask['title']
    
    twtask['project']=projconf['project']
    # add additional properties
    datedue=int(kbtask['date_due'])
    if datedue != 0:
        twtask['due']=datetime.fromtimestamp(datedue)

    vtag=next(iter([ky for ky,val in mapper['vtag.columns'].items() if val['kbid'] == kbtask['column_id']]))
    
    if vtag == 'WAITING':
        twtask['wait']=datetime.now()+timedelta(days=366)
    elif vtag == 'ACTIVE':
        if not test and not twtask.active:
            twtask.start()
    elif vtag == 'COMPLETED':
        if not test and twtask.active:
            twtask.done()
    

    #swimlane mapping
    swimlane=next(iter([ky for ky,val in mapper['uda.swimlane'].items() if val['kbid'] == kbtask['swimlane_id']]))
    twtask['swimlane']=swimlane

    cat=next(iter([ky for ky,val in mapper['uda.kbcat'].items() if val['kbid'] == kbtask['category_id']]),None)
    if cat is not None:
        twtask['kbcat']=cat
    
    if not test:
        twtask.save()
        uuid=twtask['uuid']
    else:
        uuid="testinguuid"

    return uuid,twtask

def kbFromtwTask(twtask,kbclient,mapper,projconf,kbtask=None,conflict=False,test=False):
    kbMutation={}
    
    kbMutation['title']=twtask['description']

    kbMutation['project_id']=projconf['projid']
    
    due=twtask['due']
    if due is not None:
        kbMutation['date_due']=due.strftime("%Y-%m-%d %H:%M")
    
    #determine the correct column to put the task in based on the mapped vtags
    #default vtag is the first registered one
    vtag=next(iter(mapper['vtag.columns']))
    openTask=False
    closeTask=False
    if twtask.active:
        vtag='ACTIVE'
        openTask=True
    elif twtask.completed:
        vtag='COMPLETED'
        closeTask=True
    elif twtask.waiting:
        vtag='WAITING'
    elif 'WEEK' in mapper['vtag.columns'] and due is not None:
        year, due_week, day_of_week = due.isocalendar()

        year, current_week, day_of_week = datetime.now().isocalendar()


        if due_week == current_week:
            vtag='WEEK'

    elif 'TOMORROW' in mapper['vtag.columns'] and due is not None:
        tomorrow=date.today()+timedelta(days=1)
        if tomorrow == due.date():
            vtag="TOMORROW"
    
    kbMutation['column_id']=int(next(iter([val['kbid'] for ky,val in mapper['vtag.columns'].items() if ky == vtag])))
    

    #determine the correct swimlane (or default)

    swimlane=twtask['swimlane']

    if swimlane is not None:
        kbMutation['swimlane_id']=int(next(iter([val['kbid'] for ky,val in mapper['uda.swimlane'].items() if ky == swimlane])))
    
    #determine the correct category (or None)
    cat=twtask['kbcat']
    if cat is not None:
        kbMutation['category_id']=int(next(iter([val['kbid'] for ky,val in mapper['uda.kbcat'].items() if ky == cat ])))

    if not test:
        if kbtask and conflict:
            # duplicate the existing task and mark as a conflict
            kbidconflict=kbclient.duplicateTaskToProject(task_id=kbtask['id'],project_id=projconf['projid'])
            if not kbidconflict:
                raise RuntimeError("Did not succeed to create a duplicate kanboard task")
            success=kbclient.updateTask(id=kbidconflict,title="CONFLICT"+kbtask['title'])

            if not success:
                raise RuntimeError("Did not succeed to update conflicted kanboard task")

        if kbtask is None:
            #create a new kanboard task
            kbid=kbclient.createTask(**kbMutation)
            if not kbid:
                raise RuntimeError("Did not succeed to create kanboard task")
        else:
            kbid=kbtask['id']
            kbMutation['id']=kbid
            del kbMutation['project_id']
            success=kbclient.updateTask(**kbMutation)
            if not success:
                raise RuntimeError("Did not succeed to update kanboard task")

        if kbid:
            #reretrieve newly generated or updated task from server
            kbtask=kbclient.getTask(task_id=kbid)
        
        if closeTask and kbid:
            kbclient.closeTask(task_id=kbid)
        if openTask and kbid:
            kbclient.openTask(task_id=kbid)
    else:
        kbid=-1#testng purposes only

    
    return kbid,kbtask
    
def setasSynced(cur,syncTable,kbid,uuid):
    cur.execute(f"INSERT OR REPLACE INTO {syncTable} (kbid,uuid,lastsync) VALUES(?,?,?)",(kbid,uuid,datetime.now())) 

def syncTasks(conn, project=None,test=True):
    projects=getKanboardSync(conn,project)
    lastmodTable='lastmod'

    needsyncTable='needsync'

    if type(projects) is not list:
        projects=[projects]

    for projconf in projects:
        print(f"Synchronizing Kanboard project {projconf['project']}")
        synctaskTable=f"{projconf['project'].lower()}_tasks"
        #retrieve tasks from taskwarrior

        tw=TaskWarrior(create=False)
        twtasks=tw.tasks.filter(project=projconf['project'],modified__after=projconf['lastsync'])        
        #get open kanboard tasks modified since the last sync
        if not isKanboardConnected(projconf['url']):
            return

        kb=kanboard.Client(projconf["url"],projconf["user"],projconf["apitoken"])
        qry=f"modified:>={int(projconf['lastsync'].timestamp())}"
        kbtasks=kb.searchTasks(project_id=projconf["projid"],query=qry)

        #create a temporary table with the recent modificated tasks from both kanboard and taskwarrior
        with newcur(conn) as cur:
            cur.execute(f"DROP TABLE IF EXISTS {lastmodTable}")
            cur.execute(f"CREATE TABLE {lastmodTable} (uuid TEXT UNIQUE, kbid INT UNIQUE, twmod TIMESTAMP, kbmod TIMESTAMP)")
    
            #insert twtask id's
            if len(twtasks) > 0:
                cur.executemany(f"INSERT INTO {lastmodTable} (uuid,twmod) VALUES (?,?)",[(el['uuid'],el['modified'].replace(tzinfo=None)) for el in twtasks])

            if len(kbtasks) > 0:
                cur.executemany(f"INSERT INTO {lastmodTable} (kbid,kbmod) VALUES (?,?)",[(el['id'],datetime.fromtimestamp(int(el['date_modification']))) for el in kbtasks])

            # now do a join with the sync table

            if not tableExists(conn,synctaskTable):
                cur.execute(f"""
                CREATE TABLE {synctaskTable} (uuid TEXT UNIQUE, kbid INT UNIQUE, lastsync TEXT)
                """)
            cur.execute(f"DROP TABLE IF EXISTS {needsyncTable}")
            cur.execute(f"CREATE TABLE {needsyncTable} (uuid TEXT , kbid INT , twmod TIMESTAMP, kbmod TIMESTAMP, lastsync TIMESTAMP ) ")

            cur.execute(f"""
                    INSERT INTO {needsyncTable} (kbid,uuid,twmod,kbmod,lastsync) SELECT IFNULL(synct.kbid,lmod.kbid) as kbid, IFNULL(synct.uuid,lmod.uuid) as uuid, 
                    lmod.twmod AS twmod, lmod.kbmod AS kbmod, synct.lastsync AS lastsync
                    FROM {lastmodTable} as lmod
                    LEFT JOIN {synctaskTable} as synct
                    ON synct.uuid = lmod.uuid OR synct.kbid = lmod.kbid
                    """)

            cur.execute(f"UPDATE {needsyncTable} SET lastsync = datetime('2000-01-01') WHERE lastsync IS NULL")
            cur.execute(f"UPDATE {needsyncTable} SET kbmod = datetime('2000-01-01') WHERE kbmod IS NULL")
            cur.execute(f"UPDATE {needsyncTable} SET twmod = datetime('2000-01-01') WHERE twmod IS NULL")
            tobesynced=cur.execute(f"select uuid,kbid,MAX(twmod) AS twmod,MAX(kbmod) AS kbmod,lastsync from {needsyncTable} WHERE twmod > lastsync OR kbmod > lastsync group by uuid,kbid").fetchall()
            conn.commit()
        # now perform the syncing tasks
        mapper=getMapper(projconf)

        if len(tobesynced) == 0:
            print("No tasks need to be synced")
            return

        with newcur(conn) as cur:
            for item in tobesynced:
                changed=False
                kbid=item['kbid']
                uuid=item['uuid']
                
                #try to retrieve the tasks
                if kbid is not None:
                    kbtask=next(iter([el for el in kbtasks if int(el['id']) == kbid ]), None)

                    if kbtask is None:
                        #try getting it from the server
                        kbtask=kbclient.getTask(task_id=kbid)
                else:
                    kbtask=None

                if uuid is not None:
                    twtask=next(iter([el for el in twtasks if el['uuid'] == uuid ]),None)
                    if twtask is None:
                        twtask=tw.tasks.get(uuid=uuid)
                else:
                    twtask=None
                
                twmod=datetime.strptime(item['twmod'],'%Y-%m-%d %H:%M:%S')
                kbmod=datetime.strptime(item['kbmod'],'%Y-%m-%d %H:%M:%S')
                lastsync=item['lastsync']

                #detect whether a conflict has arisen
                if (kbmod > lastsync) and (twmod > lastsync):
                    conflict=True
                    logging.debug(f"Resolving conflict..")
                else:
                    conflict=False
                #create a kanboard task from a taskwarrior task
                if twtask is not None and twmod > lastsync:
                    if kbtask is None:
                        logging.debug(f"Creating new Kanboard task from Taskwarrior task {uuid}")
                    else:
                        logging.debug(f"Updating Kanboard task {kbid} from Taskwarrior task {uuid}")

                    kbid,kbtask=kbFromtwTask(twtask,kbclient=kb,projconf=projconf,kbtask=kbtask,conflict=conflict,mapper=mapper,test=test)

                if kbtask is not None and kbmod > lastsync:
                    if twtask is None:
                        logging.debug(f"Creating new Taskwarrior task from Kanboard task {kbid}")
                    else:
                        logging.debug(f"Updating Taskwarrior task {uuid} from Kanboard task {kbid}")
                    uuid,twtask=twFromkbTask(kbtask,projconf=projconf,twtask=twtask,twclient=tw,mapper=mapper,test=test)
                if not test:
                    setasSynced(cur,synctaskTable, kbid,uuid)
                    conn.commit()
            
            #set overall sync of the database
            if not test:
                cur.execute(f"UPDATE {serverTable} SET lastsync = (?) WHERE project = '{project}'",(datetime.now(),))
        conn.commit()

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
    #open the sqlite database
    conn=openDb()

    if args.list:
        for res in getKanboardSync(conn):
            print(f"Project: {res['project']} found at {res['url']}\n registered mapping:")
            #also print mapping
            pprint(getMapper(res))
        sys.exit(0)

    if args.config:
        configKanboardSync(conn,args.project)

    if args.sync:
        if args.daemonize:
            while True:
                syncTasks(conn,args.project,args.test)
                logging.info(f"Sleeping for {args.daemonize} seconds")
                time.sleep(args.daemonize)
        else:
            syncTasks(conn,args.project,args.test)


if __name__ == "__main__":
    main(sys.argv)
