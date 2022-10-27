# Author R. Rietbroek Aug 2022
# contains functionality to interact with the sqlite database

import os
import sqlite3
from contextlib import closing
import json
from kanboard_taskwarrior.config import runConfig,configUDA
from kanboard_taskwarrior.taskmap import twFromkbTask,kbFromtwTask
from kanboard_taskwarrior.clients import kbClient, twClient,TWDoesNotExist,KBClientError,TWClientError

from uuid import uuid4
from datetime import datetime
import logging

def opendb(dbpath=None):
        if not dbpath:
            dbpath=os.path.join(os.path.expanduser('~'),".task/taskw-sync-KB.sql")
        try:
            conn=sqlite3.connect(dbpath,detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
            conn.row_factory = sqlite3.Row
        except sqlite3.Error as e:
            print(e)
            if conn:
                conn.close()


        return conn

kbserverTable='kbserver'
migrationTable='migrationhistory'

class DbConnector:
    """A class which connects toa  sqlite database and adds functionality to work with a sync-project"""
    clientversion=2
    def __init__(self,dbpath=None,test=False):

        self._dbcon=opendb(dbpath)
        #possibly migrate existing database first
        self.migrateCheck()
        #initialize the kberserver table if it doesn't exists
        self._initTable()
        self._syncentries={}
        self._test=test

    def _initTable(self,tableName=kbserverTable):
        """create the dedicated server table if it doesn't exists yet
        Note the kbserver table is a special case"""
        if self.tableExists(tableName):
            #nothing to do
            return

        if tableName == kbserverTable:
            #create the kbserver table
            with self.newcur() as cur:
                cur.execute(f"""
                CREATE TABLE {tableName} (url TEXT, apitoken TEXT, user TEXT, project TEXT UNIQUE, projid INT, assignee TEXT, mapping json, lastsync TIMESTAMP,PRIMARY KEY(project))
                """)
        elif tableName == migrationTable:
            with self.newcur() as cur:
                cur.execute(f"""
                CREATE TABLE {tableName} (version INT UNIQUE, minversion INT DEFAULT 0, migration_date TIMESTAMP,PRIMARY KEY(version))
                """)
        else:
                
            with self.newcur() as cur:
            #create a table with synced entries for a dedicated project
                cur.execute(f"""
                CREATE TABLE {tableName} (uuid TEXT UNIQUE, kbid INT UNIQUE, lastsync TEXT)
                """)
    
    def setMigration(self,version,minversion=0):
        with self.newcur() as cur:
            cur.execute(f"INSERT INTO {migrationTable} (version,migration_date,minversion) VALUES (?,?,?)",(version,datetime.now(),minversion))
            self._dbcon.commit()

    def migrateCheck(self):
        """Manage migration of the database and check client compatibility"""
        #create if it is not existing
        self._initTable(migrationTable)
        #check for database version
        with self.newcur() as cur:
            #get the newest migration
            migration=cur.execute(f"SELECT * FROM {migrationTable} ORDER BY version DESC").fetchone()
            if not migration:
                # pristine database creation -> set version to the current client version (mo need to do further migrations
                self.setMigration(self.clientversion)
                return
        
        if self.clientversion < migration['minversion']:
            raise RuntimeError(f"Client version {self.clientversion} should be larger than {migration['minversion']} to work with this database")
        
        if self.clientversion <= migration['version']:
            logging.debug(f"No need to migrate database, already at version {migration['version']}")
            return

        # if migration['version'] < 2:
            # #add an assignee column to the kbserver table
            # with self.newcur() as cur:
                # cur.execute(f"ALTER TABLE {kbserverTable} ADD COLUMN assignee TEXT")
                # cur.execute(f"INSERT INTO {migrationTable} (version,migration_date) VALUES (?,?)",(1,datetime.now()))
                # self._dbcon.commit()
        
        if migration['version'] < 3:
            #add an runtaskdsync column to the kbserver table
            with self.newcur() as cur:
                cur.execute(f"ALTER TABLE {kbserverTable} ADD COLUMN runtaskdsync TEXT")
                self._dbcon.commit()
            self.setMigration(2)


        # add other migration strategies
        # if migration['version'] < 4 ....



    def newcur(self):
        return closing(self._dbcon.cursor())


    def tableExists(self,tablename):
        tExists=False
        with self.newcur() as cur:
            cur.execute(f"""
            SELECT COUNT(*)
            FROM sqlite_master
            WHERE type = 'table'  AND name = '{tablename}'
            """)
        
            if cur.fetchone()[0] == 1:
                tExists=True
        
        return tExists

    def items(self):
        """Convenience function to return all registered syncing configurations"""
        self._fillentries()
        return self._syncentries.items()
    
    def __getitem__(self,key):
        return self._syncentries[key]

    def _fillentries(self):
        """fill sync entries if it is not done already"""
        if self._syncentries:
            return
        with self.newcur() as cur:
            res=cur.execute(f"SELECT * from {kbserverTable}").fetchall()

            for entry in res:
                projname=entry["project"]
                
                self._syncentries[projname]={ky:entry[ky] for ky in entry.keys()}
                #convert the jsonmapper to dict

                if "mapping" in entry.keys():
                    if entry["mapping"]:
                        self._syncentries[projname]["mapping"]=json.loads(entry["mapping"])
                #add the table name wher ethe synced entries can be found
                synctablename=f"{projname.lower().replace(' ','_')}_tasks"
                self._syncentries[projname]["synctable"]=synctablename
    
    def _setlastSync(self,projname):
        if not self._test:
            with self.newcur() as cur:
                cur.execute(f"UPDATE {kbserverTable} SET lastsync = (?) WHERE project = '{projname}'",(datetime.now(),))
                self._dbcon.commit()


    def remove(self,projname):
        """Remove a synchronization instance if it exists"""
        self._fillentries()
        if projname in self._syncentries:
            print(f"Deleting Project link {projname}")
            if not self._test:
                with self.newcur() as cur:
                    cur.execute(f"DROP TABLE {self._syncentries[projname]['synctable']}")
                    cur.execute(f"DELETE FROM {kbserverTable} WHERE project = '{projname}'")
                self._dbcon.commit()
        else:
            logging.info(f"Project link {projname} does not exist and needs no deletion")

    def config(self,projectname):
        self._fillentries()
        if projectname in self._syncentries:
            projconf=self._syncentries[projectname]
        else:
            projconf={}
        config=runConfig(projectname,projconf)
        
        #configure taskwarrior uda's
        configUDA(config["mapping"])
        #store the configuration in the database
        with self.newcur() as cur:
            #convert mapping to json string
            config["mapping"]=json.dumps(config["mapping"])
            values=tuple(config[ky] for ky in ["url","user","apitoken","project","projid","lastsync","mapping","runtaskdsync"])
            if not projconf:
                cur.execute(f"INSERT INTO {kbserverTable} (url,user,apitoken,project,projid,lastsync,mapping,runtaskdsync) VALUES (?,?,?,?,?,?,?,?)",values)

            else:
                cur.execute(f"UPDATE {kbserverTable} SET url = ?,user = ?, apitoken = ?,project = ?,projid = ?,lastsync = ?,mapping = ?,runtaskdsync = ? WHERE project = '{projectname}'",values)
        
        if not self._test:
            #actually commit the changes to the database
            self._dbcon.commit()
    
    def purgeTasks(self,projectname):
        """Delete tasks which were synced but for which one has been deleted"""
        self._fillentries()
        projconf=self._syncentries[projectname]

        kbclnt=kbClient(projconf["url"],projconf["user"],projconf["apitoken"])
        if kbclnt is None:
            #we can not sync if the kanboard instance is not reachable or if the user cannot be authenticated
            return
         
        twclnt=twClient()

        with self.newcur() as cur:
            syncedtasks=cur.execute(f"SELECT * from {projconf['synctable']}")

            for tasklink in syncedtasks:
                #check whether the entry is not deleted in taskwarrior
                twWasDeleted=False            
                try:
                    twtask=twclnt.tasks.get(uuid=tasklink['uuid'])
                    if twtask.deleted:
                        twWasDeleted=True

                    #check if it was a taskwarrior recurrent task (we do not want to sync those)
                    # note as of 22 sept 2022 these should not occur in the synclist anymore, so the code below was to clean up leftovers/errors
                    if twtask.recurring:
                        #fake that this task hs been deleted
                        twWasDeleted=True
                except TWDoesNotExist:
                    #cannot be found or is not deleted
                    twWasDeleted=True            
                
                kbWasDeleted=False
                try:
                    kbtask=kbclnt.getTask(task_id=tasklink['kbid'])
                except KBClientError:
                    kbWasDeleted=True
                
                if twWasDeleted and not kbWasDeleted:
                    #remove kanboard task
                    logging.info(f"removing obselete Kanboard task {tasklink['kbid']}")
                    if not self._test:
                        isremoved=kbclnt.removeTask(task_id=tasklink['kbid'])
                        if not isremoved:
                            logging.warning("could not remove kanboard task,skipping")
                            continue

                if kbWasDeleted and not twWasDeleted:
                    #remove taskwarrior task
                    logging.info(f"removing obsolete taskwarrior task {tasklink['uuid']}")
                    if not self._test:
                        twtask.delete()
                        twtask.save()
                
                if kbWasDeleted or twWasDeleted:
                    #remove the entry from the syn table
                    
                    logging.info("Removing obsolete link from database")
                    if not self._test:
                        with self.newcur() as cur:
                            cur.execute(f"DELETE FROM {projconf['synctable']} WHERE uuid = ? and kbid = ?",(tasklink['uuid'],tasklink['kbid']))
                        
                        self._dbcon.commit()

            

    def syncTasks(self,projectname=None):
        self._fillentries()
        for project,entry in self._syncentries.items():
            if projectname is not None and projectname != project:
                continue
            #create the sync table if it doesn't exist
            #sync the tasks of a single project 
            self.syncSingle(entry)

    
    def syncSingle(self,projconf):
        """sync a single project"""
        
        #initialize a taskwarrior client
        twclnt=twClient()
        if projconf["runtaskdsync"] is not None:
            if projconf["runtaskdsync"].lower() == "y":
                logging.debug("Synchronizing with taskd server")
                twclnt.sync()

        # Initialize kanboard client and check for connectivity
        kbclnt=kbClient(projconf["url"],projconf["user"],projconf["apitoken"])
        if kbclnt is None:
            #we can not sync if the kanboard instance is not reachable or if the user cannot be authenticated
            return

        print(f"Synchronizing Kanboard project {projconf['project']}")

        self._initTable(projconf['synctable'])
        randuuid=uuid4().hex[0:6]  
        #generate names for temporary tables
        lastmodTable=f'temp.lastmod_{randuuid}'
        needsyncTable=f'temp.needsync_{randuuid}'
        
        synctaskTable=projconf['synctable']

        
        # Retrieve recently modified tasks from kanboard
        qry=f"modified:>={int(projconf['lastsync'].timestamp())}"
        if projconf["assignee"] is not None:
            qry+=f" assignee:{projconf['assignee']}"
        kbtasks=kbclnt.searchTasks(project_id=projconf["projid"],query=qry)
        #remove conflicts (don't resync these back to taskwarrior as it will create infinite growth)
        kbtasks=[el for el in kbtasks if not el["title"].startswith("CONFLICT")]
        #retriev modified tasks from taskwarrior

        twtasks=twclnt.tasks.filter(project=projconf['project'],modified__after=projconf['lastsync'],status__not="Recurring")        

       ## CREATE tables to figure out which tasks are new and which ones need to be syncrhoinzed
        with self.newcur() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {lastmodTable}")#note: probably not needed for temp tables
            cur.execute(f"CREATE TABLE {lastmodTable} (uuid TEXT UNIQUE, kbid INT UNIQUE, twmod TIMESTAMP, kbmod TIMESTAMP)")

        #insert twtask modified uuid's
            if len(twtasks) > 0:
                cur.executemany(f"INSERT INTO {lastmodTable} (uuid,twmod) VALUES (?,?)",[(el['uuid'],el['modified'].replace(tzinfo=None)) for el in twtasks])

            #insert new kanboard task id's
            if len(kbtasks) > 0:
                cur.executemany(f"INSERT INTO {lastmodTable} (kbid,kbmod) VALUES (?,?)",[(el['id'],datetime.fromtimestamp(int(el['date_modification']))) for el in kbtasks])
            

            cur.execute(f"DROP TABLE IF EXISTS {needsyncTable}")#note: probably not needed for temp tables
            cur.execute(f"CREATE TABLE {needsyncTable} (uuid TEXT , kbid INT , twmod TIMESTAMP, kbmod TIMESTAMP, lastsync TIMESTAMP ) ")

            

            cur.execute(f"""
                INSERT INTO {needsyncTable} (kbid,uuid,twmod,kbmod,lastsync) 
                SELECT IFNULL(synct.kbid,lmod.kbid) AS kbid, IFNULL(synct.uuid,lmod.uuid) AS uuid,lmod.twmod AS twmod, lmod.kbmod AS kbmod, synct.lastsync AS lastsync
                FROM {lastmodTable} as lmod
                LEFT JOIN {synctaskTable} as synct
                ON synct.uuid = lmod.uuid OR synct.kbid = lmod.kbid
                """)

            cur.execute(f"UPDATE {needsyncTable} SET lastsync = datetime('2000-01-01') WHERE lastsync IS NULL")
            cur.execute(f"UPDATE {needsyncTable} SET kbmod = datetime('2000-01-01') WHERE kbmod IS NULL")
            cur.execute(f"UPDATE {needsyncTable} SET twmod = datetime('2000-01-01') WHERE twmod IS NULL")
            tobesynced=cur.execute(f"select uuid,kbid,MAX(twmod) AS twmod,MAX(kbmod) AS kbmod,lastsync from {needsyncTable} WHERE twmod > lastsync OR kbmod > lastsync group by uuid,kbid").fetchall()

        #commit the above sql operations
        self._dbcon.commit()
        if len(tobesynced) == 0:
            print("no tasks need to be synced")
            #but do set the lastsync time to now
            # self._setlastSync(projconf['project'])
            return

        with self.newcur() as cur:
            for item in tobesynced:
                kbid=item['kbid']
                uuid=item['uuid']
                
                #try to retrieve the tasks
                if kbid is not None:
                    kbtask=next(iter([el for el in kbtasks if int(el['id']) == kbid ]), None)

                    if kbtask is None:
                        #try getting it from the server
                        kbtask=kbclnt.getTask(task_id=kbid)
                else:
                    kbtask=None

                if uuid is not None:
                    twtask=next(iter([el for el in twtasks if el['uuid'] == uuid ]),None)
                    if twtask is None:
                        twtask=twclnt.tasks.get(uuid=uuid)
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

                    kbid,kbtask=kbFromtwTask(twtask,kbclient=kbclnt,projconf=projconf,kbtask=kbtask,conflict=conflict,test=self._test)

                if kbtask is not None and kbmod > lastsync:
                    if twtask is None:
                        logging.debug(f"Creating new Taskwarrior task from Kanboard task {kbid}")
                    else:
                        logging.debug(f"Updating Taskwarrior task {uuid} from Kanboard task {kbid}")
                    uuid,twtask=twFromkbTask(kbtask,projconf=projconf,twtask=twtask,twclient=twclnt,test=self._test)
                
                if not self._test:
                    cur.execute(f"INSERT OR REPLACE INTO {synctaskTable} (kbid,uuid,lastsync) VALUES(?,?,?)",(kbid,uuid,datetime.now())) 
                    self._dbcon.commit()
           
        #set overall sync of the database
        self._setlastSync(projconf['project'])


        



