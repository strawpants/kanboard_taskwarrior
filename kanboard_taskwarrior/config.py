# Author R. Rietbroek Aug 2022
# contains functionality to setup a syncing connection
import logging
from kanboard_taskwarrior.taskmap import getVtags,colkey,catkey,swimkey
from kanboard_taskwarrior.clients import kbClient,twClient,KBClientError

import sys
from copy import deepcopy
from datetime import datetime

def getDefault(projconf,key,fallback=""):
    if key in projconf.keys():
        if projconf[key] is not None:
            return projconf[key]
    
    return fallback

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

def configUDA(mapper):
    tpy="string"

    tw=twClient()
    for udaky,udamap in mapper.items():
        if not udaky.startswith("uda"):
            continue
        if not udamap:
            #nothing to add
            continue
        udaval=[ky for ky in udamap.keys()] 
        #retrieve an existing uda (to update values)

        valky=f"{udaky}.values"
        labky=f"{udaky}.label"
        typeky=f"{udaky}.type"

        udaval.extend(tw.config[valky].split(","))

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
        uniqueval=",".join(set(udaval))
        tw.execute_command(["config",valky,uniqueval])

def configMap(values,existingMap,maptype):

    aliases=[]
    for el in values:
        default=next(iter([ky for ky,val in existingMap.items() if val["kbid"] == el["id"]]),el["name"])
        aliases.append(prompt(f"Select Taskwarrior alias for Kanboard {maptype} {el['name']}",default))
        
    return {ky:{"kbid":el["id"],"name":el["name"]} for ky,el in zip(aliases,values)}

def configMapOptions(values,existingMap,maptype,optionsPool):

    availableOpts=deepcopy(optionsPool)
    #add a none option
    availableOpts[-1]="Do not set"
    aliases=[]

    for el in values:
        default=next(iter([ky for ky,val in existingMap.items() if val["kbid"] == el["id"]]),None)
        if not default:
            #take the first entry from the available options
            default=next(iter(availableOpts.values()))
        
        defaultkey=next(iter([ky for ky,val in availableOpts.items() if val == default]))
        optdescr=", ".join([f"{i}:{val}" for i,val in availableOpts.items()])
        selectedkey=prompt(f"Select Taskwarrior option for Kanboard {maptype} {el['title']},({optdescr})",defaultkey)
        #remove this option form the available ones
        if selectedkey != -1:
            #NONE option is special and can be used multiple times (it doesn't register an alias)
            aliases.append(availableOpts[selectedkey])
            del availableOpts[selectedkey] 
    
    return {ky:{"kbid":el["id"],"name":el["title"]} for ky,el in zip(aliases,values)}

def runConfig(project,projconf):
    config={"project":project}
    
    if not projconf:
        create=prompt(f"Project mapping {project} does not exist yet, create a new mapping (y/n)?","y").lower() == "y"
        
        if create:
            projconf={"mapping":{colkey:{},swimkey:{},catkey:{}}}
        else:
            logging.info("Not creating a new project mapping, quitting")
            sys.exit(0)
    
    logging.info("Setting up Kanboard- taskwarrior mapping")
    keyprompts={"url":("Enter Kanboard serveraddress",""),
            "user":("Enter your Kanboard username",""),
            "apitoken":("Enter personal Kanboard API Token (create in Kanboard under My profile -> API)",""),
            "assignee":("Enter assignee whos task need to be synced (leave empty for getting all tasks)",""),
            "runtaskdsync":("Whether to apply 'task sync' (sync with taskd server) before doing the syncing operation (y/n)","n")}

    for ky,val in keyprompts.items():
        config[ky]=prompt(val[0],getDefault(projconf,ky,val[1]))

    #possibly fix url so it start with https and ends with /jsonrpc.php
    if not config["url"].endswith('/jsonrpc.php'):
        config["url"]+="/jsonrpc.php"
    if not config["url"].startswith('http'):
        config["url"]="https://"+config["url"]
    
    #also setup mapping of this project
    kbclnt=kbClient(config["url"],config["user"],config["apitoken"])

    try:
        proj=kbclnt.getProjectByName(name=project)
    except KBClientError:
        logging.error(f"Can not find kanboard project named {project}. Does it exist and do you have access?")
        sys.exit(1)
   
    config["projid"]=proj["id"]
    config["lastsync"]=datetime(2000,1,1) #old enought o kick off a new sync
    mapper=projconf["mapping"]

     
    categories=kbclnt.getAllCategories(project_id=proj["id"])
    mapper[catkey]=configMap(categories,projconf['mapping'][catkey],"category")

    swimlanes=kbclnt.getActiveSwimlanes(project_id=proj["id"])
    mapper[swimkey]=configMap(swimlanes,projconf['mapping'][swimkey],"swimlane")
    
    columns=kbclnt.getColumns(project_id=proj["id"])
    mapper[colkey]=configMapOptions(columns,projconf['mapping'][colkey],"Column",getVtags())
    config["mapping"]=mapper
    return config
