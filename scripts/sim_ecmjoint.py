#!/usr/bin/env python

import sys
import rospy
from sensor_msgs.msg import JointState

jnt_msg = JointState()
# rate = rospy.Rate(50);     # 50 hz

def jnt_pos_cb(msg):
    global jnt_msg
    if len(msg.position) != 4:
        rospy.logerr("Error msg.position len was supposed to be 4 but is = " +
                     str(len(msg.position)))
        pass
    else:
        jnt_msg.position = []
        jnt_msg.position.append(msg.position[0])
        jnt_msg.position.append(msg.position[1])
        jnt_msg.position.append(msg.position[2] / 1000.0)
        jnt_msg.position.append(msg.position[3])
        pass

def jnt_vel_cb(msg):
    global jnt_msg
    if len(msg.velocity) != 4:
        pass
    else:
        jnt_msg.velocity = []
        for i in range(0,len(msg.velocity)):
            jnt_msg.velocity.append(msg.velocity[i])
        pass

def set_joint_angles_cb(msg):
    global rate, jnt_pub
    msg.header.stamp = rospy.Time.now()
    
    if len(msg.name) != len(msg.position):
        rospy.logerr("ERROR Size mismatch")
        rospy.logerr("len.name = " + str(len(msg.name)))
        rospy.logerr("len.pos = " + str(len(msg.position)))

    # publish jointstate
    jnt_pub.publish(msg)

def main():
    global jnt_msg
    global jnt_pub
    global rate
    
    
    # initialize ROS node
    rospy.init_node('autocamera_joint_publisher')

    # create a psm publisher
    jnt_pub = rospy.Publisher('joint_states_robot', JointState, queue_size=10)
    # create psm joint position subscriber
    jnt_pos_sub = rospy.Subscriber(
        'joint_position_current',
        JointState,
        jnt_pos_cb)
    
    # create psm joint velocity subscriber
    jnt_vel_sub = rospy.Subscriber(
        'joint_velocity_current',
        JointState,
        jnt_vel_cb)

    # initialize jnt_msg
#     jnt_msg.name = ['ecm_yaw_joint',
#                     'ecm_pitch_joint',
#                     'ecm_insertion_joint', 
#                     'ecm_roll_joint']
#     jnt_msg.position = [2, 1, 2, 1]
    
#     rate = rospy.Rate(50);     # 50 hz

    # Create a subscriber to get camera joint angles
    set_joints_sub = rospy.Subscriber(
        'autocamera_node',
        JointState,
        set_joint_angles_cb)
    
    psm1_pub = rospy.Publisher('/dvrk_psm1/joint_states', JointState, queue_size=10)
    
    rospy.spin()

# entry point
if __name__ == '__main__':
    main()

