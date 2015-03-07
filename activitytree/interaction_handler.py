#!/usr/bin/env python

from activitytree.models import ActivityTree, UserLearningActivity
import datetime
from lxml import etree
#Exceptions



class Error(Exception):
    """Base class for exceptions in this module."""
    pass


class TransitionError(Error):
    """Raised when an operation attempts a state transition that's not
    allowed.

    Attributes:
        previous -- state at beginning of transition
        next -- attempted new state
        message -- explanation of why the specific transition is not allowed
    """

    def __init__(self, previous, next, message):
        self.previous = previous
        self.next = next
        self.message = message


class NotAllowed(Error):
    """Raised when an invalid action is encounterd

    Attributes:
        action  -- action to be executed
        message -- explanation of why the specific action is not allowed
    """

    def __init__(self, action, message):
        self.action = action
        self.message = message

    def __str__(self):
        return """%s not allowed, %s""" % (self.action, self.message,)


class SimpleSequencing(object):
    def set_current(self, ula):
        atree = ula.get_atree()

        #If there is a current activity don't do anything
        if atree.current_activity:
            if atree.current_activity == ula:
                return
            else:
                raise NotAllowed('Set Current', "Another activity is already the current activity")

        # Set current activity if everything is fine 
        atree.current_activity = ula
        ula.is_current = True
        ula.save()
        atree.save()

    def get_current(self, ula):
        atree = ula.get_atree()

        if atree.current_activity:
            return atree.current_activity
        else:
            return None

    def get_path(self,current):
        while current.parent:
            yield current
            current = current.parent
        if not current.parent:
            yield current

    def get_current_path(self, current):
        path = [la for la in self.get_path(current.learning_activity)]
        path.reverse()
        return path



    def exit(self, ula, progress_status=None, objective_status=None, objective_measure=None, kmdynamics=None, attempt=False):

        atree = ActivityTree.objects.get(user=ula.user, root_activity=ula.learning_activity.get_root())

        if not ula.is_current:
            raise NotAllowed('Set Current', "Can only exit a current activity")
            #pass
        else:
            ula.is_current = False
            atree.current_activity = None
            if progress_status:
                ula.progress_status = progress_status
            if objective_status:
                ula.objective_status = objective_status
            if objective_measure is not None:
                ula.objective_measure = objective_measure
            if kmdynamics is not None:
                ula.kmdynamics = kmdynamics
            ula.last_visited = datetime.datetime.now()
            if attempt:
                ula.num_attempts += 1
            ula.save()
            atree.save()
            ula.rollup_rules()

    def update(self, ula, progress_status=None, objective_status=None, objective_measure=None, attempt=False):
        if not ula.is_current:
            raise NotAllowed('Update', "Can only update a current activity")
        else:
            if progress_status is not None:
                ula.progress_status = progress_status
            if objective_status is not None :
                ula.objective_status = objective_status
            if objective_measure is not None:
                ula.objective_measure = objective_measure
            ula.last_visited = datetime.datetime.now()
            if attempt:
                ula.num_attempts += 1
            ula.save()

    def suspend(self, user, activity):
        pass

    def resume(self, user, activity):
        pass

    def assignActivityTree(self, user, activity):
        #Only root activities can be assigned
        if activity.parent is None:
            #If Root bring a List of all child nodes recursive
            nodeList = activity.get_children(recursive=True)
            #Plus root
            nodeList.append(activity)
            #Create another tree of UserLearningActiviy instances
            #All init at default values
            for node in nodeList:
                ula = UserLearningActivity(user=user, learning_activity=node)
                ula.save()
            #Create an instance of ActivityTree
            atree = ActivityTree(user=user, root_activity=activity)
            atree.save()
        else:
            raise NotAllowed('Assign Activity Tree', "Only Root Nodes can be assigned")

    def get_next(self, ula, current):

        #current = self.get_current(ula)

        if current:
            nav = self.get_nav(ula)
            XML = self.nav_to_xml(root=nav)
            eroot = etree.XML(XML)
            navlist = [e for e in eroot.iter()]
            current_found = False
            for i, item in enumerate(navlist):
                if (item.get("uri") == current.learning_activity.uri) or current_found:
                    current_found = True
                    if i + 1 >= len(navlist):
                        return None
                    next = navlist[i + 1]

                    if next.get("is_container") == "False" and next.get("pre_condition") <> "disabled":
                        return next.get("uri")
            return None
        else:
            return None

    def get_prev(self, ula, current):

        #current = self.get_current(ula)

        if current:
            nav = self.get_nav(ula)
            XML = self.nav_to_xml(root=nav)
            eroot = etree.XML(XML)
            navlist = [e for e in eroot.iter()]
            navlist.reverse()
            current_found = False
            for i, item in enumerate(navlist):
                if (item.get("uri") == current.learning_activity.uri) or current_found:
                    current_found = True
                    if i + 1 >= len(navlist):
                        return None
                    next = navlist[i + 1]

                    if next.get("is_container") == "False" and next.get("pre_condition") <> "disabled":
                        return next.get("uri")
            return None
        else:
            return None


    def get_nav(self, ula):
        #print "get_nav call",ula
        #If nodes is None we are at root
        if ula.learning_activity.parent is None:
            #Refresh root in case it was changed elsewhere
            ula = UserLearningActivity.objects.get(id=ula.id)
            ula.children = []
        #Get children activities
        children = ula.get_children(recursive=False)
        if children:
            #Process child nodes-*
            for child in children:
                child.children = []
                child.eval_pre_condition_rule()

                #IF Parent ForwardOnly is True, disable if already tried
                #print child.learning_activity.uri, child.pre_condition
                if child.pre_condition == 'stopForwardTraversal':
                    ula.children.append(child)
                    return ula
                elif child.pre_condition == 'skip':
                    pass
                elif ula.learning_activity.forward_only and child.num_attempts > 0:
                    child.pre_condition = 'disabled'
                    ula.children.append(self.get_nav(child))
                else:
                    # disabled, hidden are still returned
                    ula.children.append(self.get_nav(child))

            return ula
        else:

            #no more nodes to process return nodes
            ula.children = []
            return ula


    def nav_to_xml(self, node=None, s="", root=None):
        open_tag_template = '<item activity = "%s"  uri = "%s"   identifier = "%s" is_current = "%s" is_container  = "%s" pre_condition = "%s"  recomended_value = "%s" objective_status ="%s" objective_measure ="%s" is_visible ="%s" heading ="%s" secondary_text="%s" description="%s" image ="%s" num_attempts="%s" attempt_limit="%s">'
        single_tag_template = open_tag_template[:-1]+'/>'
        if node is None:
            node = root
        vals = (node.learning_activity.id, node.learning_activity.uri, node.learning_activity.name, node.is_current,
                node.learning_activity.is_container, node.pre_condition,
                node.recommendation_value,
                node.objective_status, node.objective_measure,node.learning_activity.is_visible,
                node.learning_activity.heading,node.learning_activity.secondary_text,node.learning_activity.description,node.learning_activity.image,
                node.num_attempts,node.learning_activity.attempt_limit)
        if len(node.children) > 0:

            s += open_tag_template % vals
            for child in node.children:
                s += self.nav_to_xml(node=child)
            s += '</item>'
            return s
        else:
            s += single_tag_template % vals
            return s




