from __future__ import division

import sys
import rospy
import roslib
import xacro
import re
import math
import numpy
import pdb
import os
import hrl_geom
import geometry_msgs

from hrl_geom.pose_converter import PoseConv
from hrl_geom import transformations
from geometry_msgs.msg import Point

from visualization_msgs.msg import Marker

from sensor_msgs.msg import JointState
from sensor_msgs.msg import CameraInfo

from math import acos, atan2, cos, pi, sin
from numpy import array, cross, dot, float64, hypot, zeros, rot90
from numpy.linalg import norm
from urdf_parser_py.urdf import URDF
from pykdl_utils.kdl_kinematics import KDLKinematics
from visualization_msgs.msg._Marker import Marker
import image_geometry

ecm_robot = None
ecm_kin = None

psm1_robot = None
psm1_kin = None

psm2_robot = None
psm2_kin = None


def dotproduct(v1, v2):
#     rospy.logerr("v1 = "+ v1.__str__())
    return sum((a*b) for a, b in zip(v1, v2))

def length(v):
    return math.sqrt(dotproduct(v, v))

def angle(v1, v2):
    return math.acos(dotproduct(v1, v2) / (length(v1) * length(v2)))
  
def column(matrix, i):
    return [row[i] for row in matrix]

def find_rotation_matrix_between_two_vectors(a,b):
    a = numpy.array(a).reshape(1,3)[0].tolist()
    b = numpy.array(b).reshape(1,3)[0].tolist()
    
    vector_orig = a / norm(a)
    vector_fin = b / norm(b)
#     rospy.logerr('a = ' + vector_orig.__str__())
#     rospy.logerr('b = ' + vector_fin.__str__())
                 
    # The rotation axis (normalised).
    axis = cross(vector_orig, vector_fin)
    axis_len = norm(axis)
    if axis_len != 0.0:
        axis = axis / axis_len

    # Alias the axis coordinates.
    x = axis[0]
    y = axis[1]
    z = axis[2]

    # The rotation angle.
    angle = acos(dot(vector_orig, vector_fin))

    # Trig functions (only need to do this maths once!).
    ca = cos(angle)
    sa = sin(angle)
    R = numpy.identity(3)
    # Calculate the rotation matrix elements.
    R[0,0] = 1.0 + (1.0 - ca)*(x**2 - 1.0)
    R[0,1] = -z*sa + (1.0 - ca)*x*y
    R[0,2] = y*sa + (1.0 - ca)*x*z
    R[1,0] = z*sa+(1.0 - ca)*x*y
    R[1,1] = 1.0 + (1.0 - ca)*(y**2 - 1.0)
    R[1,2] = -x*sa+(1.0 - ca)*y*z
    R[2,0] = -y*sa+(1.0 - ca)*x*z
    R[2,1] = x*sa+(1.0 - ca)*y*z
    R[2,2] = 1.0 + (1.0 - ca)*(z**2 - 1.0)
    
    R = numpy.matrix(R)
    return R 
    
    
def extract_positions(joint, arm_name, joint_kin=None):
    global ecm_robot, ecm_kin, psm1_robot, psm1_kin, psm2_robot, psm2_kin
    
    arm_name = arm_name.lower()
    if ecm_robot is None:
        ecm_robot = URDF.from_parameter_server('/dvrk_ecm/robot_description')
        ecm_kin = KDLKinematics(ecm_robot, ecm_robot.links[0].name, ecm_robot.links[-1].name)
    if psm1_robot is None:
        psm1_robot = URDF.from_parameter_server('/dvrk_psm1/robot_description')
        psm1_kin = KDLKinematics(psm1_robot, psm1_robot.links[0].name, psm1_robot.links[-1].name)
    if psm2_robot is None:
        psm2_robot = URDF.from_parameter_server('/dvrk_psm2/robot_description')
        psm2_kin = KDLKinematics(psm2_robot, psm2_robot.links[0].name, psm2_robot.links[-1].name)
    
    if arm_name=="ecm": joint_kin = ecm_kin
    elif arm_name =="psm1" : joint_kin = psm1_kin
    elif arm_name =="psm2" : joint_kin = psm2_kin
            
    pos = []
    name = []
    effort = []
    velocity = []

    new_joint = JointState()
    for i in range(len(joint.position)):
        if joint.name[i] in joint_kin.get_joint_names():
            pos.append(joint.position[i])
            name.append(joint.name[i])
    new_joint.name = name
    new_joint.position = pos
    return new_joint
            
def add_marker(pose, name, color=[1,0,1], type=Marker.SPHERE, scale = [.02,.02,.02], points=None):
    vis_pub = rospy.Publisher(name, Marker, queue_size=10)
    marker = Marker()
    marker.header.frame_id = "world"
    marker.header.stamp = rospy.Time() 
    marker.ns = "my_namespace"
    marker.id = 0
    marker.type = type
    marker.action = Marker.ADD
    
    if type == Marker.LINE_LIST:
        for point in points:
            p = Point()
            p.x = point[0]
            p.y = point[1]
            p.z = point[2]
            marker.points.append(p)
    else:
        r = find_rotation_matrix_between_two_vectors([1,0,0], [0,0,1])
        rot = pose[0:3,0:3] * r
        pose2 = numpy.matrix(numpy.identity(4))
        pose2[0:3,0:3] = rot
        pose2[0:3,3] = pose[0:3,3]
        quat_pose = PoseConv.to_pos_quat(pose2)
        
        marker.pose.position.x = quat_pose[0][0]
        marker.pose.position.y = quat_pose[0][1]
        marker.pose.position.z = quat_pose[0][2]
        marker.pose.orientation.x = quat_pose[1][0]
        marker.pose.orientation.y = quat_pose[1][1] 
        marker.pose.orientation.z = quat_pose[1][2]
        marker.pose.orientation.w = quat_pose[1][3] 
        
    marker.scale.x = scale[0]
    marker.scale.y = scale[1]
    marker.scale.z = scale[2]
    marker.color.a = .5
    marker.color.r = color[0]
    marker.color.g = color[1]
    marker.color.b = color[2]
    
    
    
    vis_pub.publish(marker)
    

def point_towards_midpoint(clean_joints, psm1_pos, psm2_pos, key_hole,ecm_pose):
    mid_point = (psm1_pos + psm2_pos)/2
#     mid_point = ecm_pose[0:3,3] - numpy.array([0,0,.01]).reshape(3,1)
    add_marker(PoseConv.to_homo_mat([mid_point, [0,0,0]]), '/marker_subscriber',color=[1,0,0], scale=[0.047/5,0.047/5,0.047/5])
    add_marker(PoseConv.to_homo_mat([key_hole,[0,0,0]]), '/keyhole_subscriber',[0,0,1])
    add_marker(ecm_pose, '/current_ecm_pose', [1,0,0], Marker.ARROW, scale=[.1,.005,.005])
#     rospy.logerr('old_ecm_pose = ' +  ecm_pose.__str__())
    temp = clean_joints['ecm'].position
    b,_ = ecm_kin.FK([temp[0],temp[1],.14,temp[3]])
    # find the equation of the line that goes through the key_hole and the 
    # mid_point
    ab_vector = (mid_point-key_hole)
    ecm_current_direction = b-key_hole 
    add_marker(ecm_pose, '/midpoint_to_keyhole', [0,1,1], type=Marker.LINE_LIST, scale = [0.005, 0.005, 0.005], points=[b, key_hole])
    
    add_marker(PoseConv.to_homo_mat([ab_vector,[0,0,0]]), '/ab_vector',[0,1,0], type=Marker.ARROW)
    r = find_rotation_matrix_between_two_vectors(ecm_current_direction, ab_vector)
    m = math.sqrt(ab_vector[0]**2 + ab_vector[1]**2 + ab_vector[2]**2) # ab_vector's length
    
    # insertion joint length
    l = math.sqrt( (ecm_pose[0,3]-key_hole[0])**2 + (ecm_pose[1,3]-key_hole[1])**2 + (ecm_pose[2,3]-key_hole[2])**2)
    
    # Equation of the line that passes through the midpoint of the tools and the key hole
    x = lambda t: key_hole[0] + ab_vector[0] * t
    y = lambda t: key_hole[1] + ab_vector[1] * t
    z = lambda t: key_hole[2] + ab_vector[2] * t
    
    t = l/m
    
    new_ecm_position = numpy.array([x(t), y(t), z(t)]).reshape(3,1)
    
    ecm_pose[0:3,0:3] =  r* ecm_pose[0:3,0:3]  
    ecm_pose[0:3,3] = new_ecm_position
    add_marker(ecm_pose, '/target_ecm_pose', [0,0,1], Marker.ARROW, scale=[.1,.005,.005])
    output_msg = clean_joints['ecm']
    
    
    try:
        p = ecm_kin.inverse(ecm_pose)
    except Exception as e:
        rospy.logerr('error')
    if p != None:  
        p[3] = 0
        output_msg.position = p
    return output_msg

def zoom_fitness(cam_info, mid_point, inner_margin, deadzone_margin, tool_point):
    x = cam_info.width; y = cam_info.height
#     mid_point = [x/2, y/2]
    
    # if tool in inner zone
    if abs(tool_point[0]-mid_point[0]) <= inner_margin * x/2 and abs(tool_point[1] - mid_point[1]) < inner_margin * y/2:
        return min((x/2) * inner_margin , (y/2) * inner_margin) - min([abs(tool_point[0]-mid_point[0])/(x/2),abs(tool_point[1] - mid_point[1])/(y/2)])
    # if tool in deadzone
    elif abs(tool_point[0]-mid_point[0]) <= deadzone_margin * x/2 and abs(tool_point[1] - mid_point[1]) < deadzone_margin * y/2:
        return 0
    #if tool in outer zone
    elif abs(tool_point[0]-mid_point[0]) <= x/2 and abs(tool_point[1] - mid_point[1]) <  y/2:
        return -min( [ abs(min([abs(tool_point[0] - x), tool_point[0]])-(deadzone_margin * (x/2)))/(x/2),  abs(min([abs(tool_point[1] - y), tool_point[1]]) - deadzone_margin*(y/2))/(y/2)])
    else:
        return -.1
        
def find_zoom_level(msg, cam_info, ecm_kin, psm1_kin, psm2_kin, clean_joints):
    if cam_info != None:
        T1W = psm1_kin.forward(clean_joints['psm1'].position)
        T2W = psm2_kin.forward(clean_joints['psm2'].position)
        TEW = ecm_kin.forward(clean_joints['ecm'].position)
        TEW_inv = numpy.linalg.inv(TEW)
        
        mid_point = (T1W[0:4,3] + T2W[0:4,3])/2
        p1 = T1W[0:4,3]
        p2 = T2W[0:4,3]
        
        T2E = TEW_inv * T2W
       
        ig = image_geometry.PinholeCameraModel()
        ig.fromCameraInfo(cam_info)
        x1, y1 = ig.project3dToPixel( (TEW_inv * T1W)[0:3,3])
        x2, y2 = ig.project3dToPixel( (TEW_inv * T2W)[0:3,3])
        xm, ym = ig.project3dToPixel( (TEW_inv * mid_point)[0:3,0])
        
        msg.position[3] = 0
        zoom_percentage = zoom_fitness(cam_info=cam_info, mid_point=[xm, ym], inner_margin=.10,
                                        deadzone_margin= .70, tool_point= [x1,y1])
        rospy.logerr(zoom_percentage)
        msg.position[2] =  msg.position[2] + msg.position[2] * zoom_percentage 
        if msg.position[2] < 0 :
            msg.position[2] = 0
        elif msg.position[2] > .23:
            msg.position[2] = .23
    return msg

def compute_viewangle(joint, cam_info):
    
    global ecm_robot, ecm_kin, psm1_robot, psm1_kin, psm2_robot, psm2_kin
    if ecm_robot is None:
        ecm_robot = URDF.from_parameter_server('/dvrk_ecm/robot_description')
        ecm_kin = KDLKinematics(ecm_robot, ecm_robot.links[0].name, ecm_robot.links[-1].name)
    if psm1_robot is None:
        psm1_robot = URDF.from_parameter_server('/dvrk_psm1/robot_description')
        psm1_kin = KDLKinematics(psm1_robot, psm1_robot.links[0].name, psm1_robot.links[-1].name)
    if psm2_robot is None:
        psm2_robot = URDF.from_parameter_server('/dvrk_psm2/robot_description')
        psm2_kin = KDLKinematics(psm2_robot, psm2_robot.links[0].name, psm2_robot.links[-1].name)

    
    kinematics = lambda name: psm1_kin if name == 'psm1' else psm2_kin if name == 'psm2' else ecm_kin 
    clean_joints = {}
    try:
        joint_names = joint.keys()
        for j in joint_names:
            clean_joints[j] = extract_positions(joint[j], j, kinematics(j))
    
        key_hole, _ = ecm_kin.FK([0,0,0,0]) # The position of the keyhole, is the end-effector's
        psm1_pos,_ = psm1_kin.FK(clean_joints['psm1'].position)
        psm2_pos,_ = psm2_kin.FK(clean_joints['psm2'].position)
        psm1_pose = psm1_kin.forward(clean_joints['psm1'].position)
        ecm_pose = ecm_kin.forward(clean_joints['ecm'].position)
    except Exception as e:
#         rospy.logerr(e.message)
        output_msg = joint['ecm']
#         output_msg.name = ['outer_yaw', 'outer_pitch', 'insertion', 'outer_roll']
#         output_msg.position = [joint['ecm'].position[x] for x in [0,1,5,6]]
        return output_msg
    
    output_msg = clean_joints['ecm']
    
    output_msg = point_towards_midpoint(clean_joints, psm1_pos, psm2_pos, key_hole, ecm_pose)
    output_msg = find_zoom_level(output_msg, cam_info, ecm_kin, psm1_kin, psm2_kin, clean_joints)
    
    if len(output_msg.name) > 4:
        output_msg.name = ['outer_yaw', 'outer_pitch', 'insertion', 'outer_roll']
    if len(output_msg.position) >= 7:
        output_msg.position = [output_msg.position[x] for x in [0,1,5,6]]
        
    return output_msg

    