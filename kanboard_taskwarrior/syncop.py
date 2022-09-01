# Author R. Rietbroek Aug 2022
# contains the functionality to synchronize taskwarrior and Kanboard tasks

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

