import numpy as np
import queue



class CameraMovementScaling:
    #This is a class that will start queues of tool movement and return a
    #value based on how much movement has happned with respect to a particular tool
    # for instance, if the left tool moves more than the right, the viepoint is \
    # scaled towards the left tool.  This is untested code. 

    def __init__(self):
        self.viewpoint = 0 # this is the returned ratio of the tool based on motion.
        
        #setup for two queues
        self.reaction_frames = 500 # 100 frames/ sec for 5 seconds.
        self.ltool_history = queue.Queue(maxsize= self.reaction_frames)
        self.rtool_history = queue.Queue(maxsize= self.maxsize) 
        self.P = 1
        self.I = 1
        self.D = 1
        
    
    def UpdateCameraPosition(self, ltool, rtool):
        #if the history is full, remove the oldest value.
        if self.ltool_history.full():
            #remove an element from both.  FIFO... adds to the back removes from front.
            self.ltool_history.get()
            self.rtool_history.get()       
        #add the new values to the queue
        self.ltool_history.put (ltool)
        self.rtool_history.put (rtool)

        #Should we wait until we have a full queue?

        #The proportiaonal term does not take movment into account
        left_tool_movement_p = ltool
        right_tool_movement_p = rtool
        
        #Take the derivitive of the tool movements thusfar and add them together.
        left_tool_movement_d  = np.average(np.diff(list(self.ltool_history)))
        right_tool_movement_d = np.average (diff(list(self.ltool_history)))
        
        #Take the integral of the tool movment derivities.
        left_tool_movement_i  = np.sum(np.diff(list(self.ltool_history)))
        right_tool_movement_i = np.sum (diff(list(self.ltool_history)))
        
        #Calculate all the relative terms:
        
        #if there is no movement, just return the mid point of the tools
        if (left_tool_movement_i + right_tool_movement_i) == 0:
            self.viewpoint = (ltool + rtool)/2
        else: #if there is movment
            #compute the relative movment of each tool (0-1)
            #relative influence of derivitive of the tools
            relative_left_d = left_tool_movement_d/ (left_tool_movement_d + right_tool_movement_d)
            relative_right_d = 1.0 - relative_left_d
            
            #reletive influence of the integral of the delta of the tools
            relative_left_i = left_tool_movement/ (left_tool_movement + right_tool_movement);
            relative_right_i = 1.0 - relative_left

            #squew the midpoint between the left and right tool based on movement...left off here
            # need an equation that combines all the above.
            self.viewpoint = (ltool* relative_left + rtool * relative_right)
        
        return self.viewpoint
    
    def ChangePID (self, p, i, d, reaction_frames):
        self.P = p
        self.I = i
        self.D = d
        self.reaction_frames = reaction_frames

