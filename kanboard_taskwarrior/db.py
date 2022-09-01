# Author R. Rietbroek Aug 2022
# contains functionality to interact with the sqlite database

import os
import sqlite3
from contextlib import closing
import json
from kanboard_taskwarrior.config import runConfig,configUDA

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

class DbConnector:
    """A class which connects toa  sqlite database and adds functionality to work with a sync-project"""
    def __init__(self,dbpath=None,test=False):

        self._dbcon=opendb(dbpath)
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
                CREATE TABLE {tableName} (url TEXT, apitoken TEXT, user TEXT, project TEXT UNIQUE, projid INT,  mapping json, lastsync TIMESTAMP,PRIMARY KEY(project))
                """)
        else:
                
            with self.newcur() as cur:
            #create a table with synced entries for a dedicated project
                cur.execute(f"""
                CREATE TABLE {tableName} (uuid TEXT UNIQUE, kbid INT UNIQUE, lastsync TEXT)
                """)

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
                if "mapping" in entry.keys():
                    mapper=json.loads(entry["mapping"])
                else:
                    mapper={}
                projname=entry["project"]
                self._syncentries[projname]={"project":projname,
                        "mapping":mapper,
                        "url":entry["url"],"user":entry["user"],
                        "apitoken":entry["apitoken"],
                        "lastsync":entry["lastsync"],
                        "synctable":f"{projname.lower()}_tasks"}
        
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
            values=tuple(config[ky] for ky in ["url","user","apitoken","project","projid","lastsync","mapping"])
            if not projconf:
                cur.execute(f"INSERT INTO {kbserverTable} (url,user,apitoken,project,projid,lastsync,mapping) VALUES (?,?,?,?,?,?,?)",values)

            else:
                cur.execute(f"UPDATE {kbserverTable} SET url = ?,user = ?, apitoken = ?,project = ?,projid = ?,lastsync = ?,mapping = ? WHERE project = '{projectname}'",values)
        
        if not self._test:
            #actually commit the changes to the database
            self._dbcon.commit()
    
    def syncTasks(self,projectname=None,test=False):
        self._fillentries()
        for project,entry in self._syncentries.items():
            if projectname is not None and projectname != project:
                continue
            print(f"Synchronizing Kanboard project {project}")
            #sync operation




# def setasSynced(cur,syncTable,kbid,uuid):
    # cur.execute(f"INSERT OR REPLACE INTO {syncTable} (kbid,uuid,lastsync) VALUES(?,?,?)",(kbid,uuid,datetime.now())) 

