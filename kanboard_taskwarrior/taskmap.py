# Author R. Rietbroek Aug 2022
# contains functionality to map kanboard tasks to taskwarrior tasks and vice versa


from collections import OrderedDict
from kanboard import ClientError
from tasklib import Task
from datetime import datetime,timedelta,date
import logging
def getVtags():

    vtags=OrderedDict()

    vtags[0]="WAITING"
    vtags[1]="ACTIVE"
    vtags[2]="WEEK"
    vtags[3]="TOMORROW"
    vtags[4]="COMPLETED"
    return vtags

colkey="vtag.columns"
catkey="uda.kbcat"
swimkey="uda.swimlane"

def twFromkbTask(kbtask,twclient,projconf,twtask=None,test=False):
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

    vtag=next(iter([ky for ky,val in projconf["mapping"]['vtag.columns'].items() if int(val['kbid']) == kbtask['column_id']]),"NONE")
    if vtag == 'WAITING':
        if twtask.active:
            #stop the task if it's active
            twtask.stop()
        #set wait date a year from now
        twtask['wait']=datetime.now()+timedelta(days=366)
        twtask.save()
    elif vtag == 'ACTIVE':
        if not test and not twtask.active and not twtask.completed:
            twtask.save()
            #also unset the waiting date if it has one so it will become visible
            if twtask.waiting:
                twtask['wait']=None
            twtask.start()
            twtask.save()
    elif vtag == 'COMPLETED':
        if not test and not twtask.completed and not twtask.deleted:
            twtask.save()
            twtask.done()
    elif vtag == 'WEEK':
        if twtask.waiting:
            #unset waiting state
            twtask['wait']=None
            twtask.save()

    #swimlane mapping
    
    swimlane=next(iter([ky for ky,val in projconf["mapping"]['uda.swimlane'].items() if int(val['kbid']) == kbtask['swimlane_id']]))
    twtask['swimlane']=swimlane

    cat=next(iter([ky for ky,val in projconf["mapping"]['uda.kbcat'].items() if int(val['kbid']) == kbtask['category_id']]),None)
    if cat is not None:
        twtask['kbcat']=cat
    
    if not test:
        twtask.save()
        uuid=twtask['uuid']
    else:
        uuid="testinguuid"

    return uuid,twtask

def kbFromtwTask(twtask,kbclient,projconf,kbtask=None,conflict=False,test=False):
    kbMutation={}
    
    kbMutation['title']=twtask['description']

    kbMutation['project_id']=projconf['projid']
    
    due=twtask['due']
    if due is not None:
        kbMutation['date_due']=due.strftime("%Y-%m-%d %H:%M")

    #possibly add assignee
    if projconf['assignee']:
        kbMutation['owner_id']=projconf['assignee']['kbid']
    #determine the correct column to put the task in based on the mapped vtags
    #default vtag is the first registered one
    vtag=next(iter(projconf["mapping"]['vtag.columns']))
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
    elif 'WEEK' in projconf["mapping"]['vtag.columns'] and due is not None:
        year, due_week, day_of_week = due.isocalendar()

        year, current_week, day_of_week = datetime.now().isocalendar()


        if due_week == current_week:
            vtag='WEEK'

    elif 'TOMORROW' in projconf["mapping"]['vtag.columns'] and due is not None:
        tomorrow=date.today()+timedelta(days=1)
        if tomorrow == due.date():
            vtag="TOMORROW"
    else:
       #Trigger the default column
       vtag="NONE"

    if vtag != "NONE": 
        kbMutation['column_id']=int(next(iter([val['kbid'] for ky,val in projconf["mapping"]['vtag.columns'].items() if ky == vtag])))

    #determine the correct swimlane (or default)

    swimlane=twtask['swimlane']

    if swimlane in projconf["mapping"]["uda.swimlane"]:
        # import pdb;pdb.set_trace()
        kbMutation['swimlane_id']=int(projconf["mapping"]['uda.swimlane'][swimlane]['kbid'])

    #determine the correct category (or None)
    cat=twtask['kbcat']

    if cat is not None:
        try:
            kbMutation['category_id']=int(next(iter([val['kbid'] for ky,val in projconf["mapping"]['uda.kbcat'].items() if ky == cat ])))
        except StopIteration:
            logging.warning(f"Taskwarrior category {cat} not found in mapping, ignoring")
            
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
            kbid=int(kbtask['id'])
            updateMutation={ky:kbMutation[ky] for ky in ("title","category_id","date_due") if ky in kbMutation}
            updateMutation["id"]=kbid
            success=kbclient.updateTask(**updateMutation)
            if not success:
                raise RuntimeError("Did not succeed to update kanboard task")
            
            if "column_id" in kbMutation or "swimlane_id" in kbMutation:

                moveMutation={ky:int(kbMutation[ky]) for ky in ("column_id","swimlane_id","project_id") if ky in kbMutation}
                moveMutation["task_id"]=kbid#note the kanboard movetaskPosition call expects the task id not as id but as task_id 
                moveMutation["position"]=1 #put at the top 
                try:
                    success=kbclient.moveTaskPosition(**moveMutation)
                except ClientError:
                    logging.warning("Did not succeed to move kanboard task, no change in position?")
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
