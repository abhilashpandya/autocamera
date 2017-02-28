import rospy
from sensor_msgs import msg 
from robot import robot
import numpy as np
from urdf_parser_py.urdf import URDF
from pykdl_utils.kdl_kinematics import KDLKinematics
from types import NoneType
from sensor_msgs.msg._JointState import JointState

class Joystick:
    class MODE:
        """
            simulation mode: Use the hardware for the master side, 
                            and simulation for the ECM
            hardware mode: Use hardware for both the master side,
                            and the ECM
        """
        simulation = "SIMULATION"
        hardware = "HARDWARE"
        
    def __init__(self, mode = MODE.simulation):        
        self.__mode__ = mode
        self.joint_angles = []
        self.center = [0,0,0,0]
        self.joystick_at_zero = True
        self.movement_scale = .2 
        
        self.__init_nodes__()
        self.__spin__()
        
    def __init_nodes__(self):
        rospy.init_node('ecm_joystick_control')
        
        self.ecm_hw = robot("ECM")
        self.ecm_sim = rospy.Publisher('/dvrk_ecm/joint_states_robot', JointState, queue_size=10)
        self.ecm_robot = URDF.from_parameter_server('/dvrk_ecm/robot_description')
        self.ecm_kin = KDLKinematics(self.ecm_robot, self.ecm_robot.links[0].name, self.ecm_robot.links[-1].name)
        
        if self.__mode__ == self.MODE.simulation:
            rospy.Subscriber('/dvrk_ecm/joint_states', JointState, self.ecm_cb)
        elif self.__mode__ == self.MODE.hardware:
            rospy.Subscriber('/dvrk/ECM/state_joint_current', JointState, self.ecm_cb)
            self.ecm_hw.home()
            self.ecm_hw.move_joint_list([0.0,0.0,0.0,0.0], interpolate=True)
            
        rospy.Subscriber('/joy', msg.Joy, self.on_joystick_change_cb)
        
    def __spin__(self):
        rospy.spin()

    def ecm_cb(self, msg):
        if self.__mode__ == self.MODE.simulation:
            self.joint_angles = msg.position[0:2] + msg.position[-2:]
        elif self.__mode__ == self.MODE.hardware:
            self.joint_angles = msg.position[0:2] + (0,0)
    
    def ecm_joystick_recenter(self):
        self.center = self.joint_angles
        self.joystick_at_zero = False        
    def on_joystick_change_cb(self, message):
        j = msg.Joy()
        if sum( np.abs(message.axes[0:2])) != 0 and self.joystick_at_zero == False:
            return
        self.joystick_at_zero = True
        
        if message.buttons[0] == 1:
                self.ecm_joystick_recenter()
                print('self.center = {}, self.joint_angles = {}'.format(self.center, self.joint_angles))
                
                
        elif message.axes[3] > .7 and self.joystick_at_zero == True: # The throttle 
            # Allow movement
            movement_vector = np.array(message.axes[0:2]) # left right and up down
                
            self.ecm_pan_tilt(movement_vector) 
    
    def ecm_pan_tilt(self, movement_vector):
        q = []
        q = self.joint_angles
        
        if q:            
            q = list(q)
            q[0] = movement_vector[0] * self.movement_scale
            q[1] = movement_vector[1] * self.movement_scale
            q = [round(i,4) for i in q]
            q = [i+j for i,j in zip(self.center, q)]
            print(q)
            self.move_ecm(q)
    
    # move ecm based on joint angles either in simulation or hardware
    def move_ecm(self, joint_angles):
        if self.__mode__ == self.MODE.simulation:
            msg = JointState()
            msg.position = joint_angles
            msg.name = ['outer_yaw', 'outer_pitch', 'insertion', 'outer_roll']
            self.ecm_sim.publish(msg)            
        elif self.__mode__ == self.MODE.hardware:
            self.ecm_hw.move_joint_list(joint_angles, interpolate=False)
#             rospy.sleep(.01)
        
if __name__ == "__main__":
    j = Joystick( Joystick.MODE.hardware)
    
    