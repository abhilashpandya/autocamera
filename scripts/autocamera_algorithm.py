# TO DO: Write interpolation function that returns a list of interpolated data
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
import cv2
import tf

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
import time

class Autocamera:
    DEBUG = False # Print debug messages?
    
    def __init__(self):
        self.ecm_robot = URDF.from_parameter_server('/dvrk_ecm/robot_description')
        self.ecm_kin = KDLKinematics(self.ecm_robot, self.ecm_robot.links[0].name, self.ecm_robot.links[-1].name)
        
        self.psm1_robot = URDF.from_parameter_server('/dvrk_psm1/robot_description')
        self.psm1_kin = KDLKinematics(self.psm1_robot, self.psm1_robot.links[0].name, self.psm1_robot.links[-1].name)
        
        self.psm2_robot = URDF.from_parameter_server('/dvrk_psm2/robot_description')
        self.psm2_kin = KDLKinematics(self.psm2_robot, self.psm2_robot.links[0].name, self.psm2_robot.links[-1].name)
        
        
        self.tool_timer = {'last_psm1_pos':None, 'last_psm2_pos':None, 'psm1_stay_start_time':0, 'psm2_stay_start_time':0, 'psm1_stationary_duration':0, 'psm2_stationary_duration':0}
        
        
        self.last_midpoint = None
        self.midpoint_time = 0
        self.pan_tilt_deadzone_radius = .001
        
        self.zoom_deadzone_radius = .2
        self.zoom_innerzone_radius = .1
        self.zones_times = {'inner_zone':0, 'outer_zone':0} # Keep track of how long the tools are in each of these 2 zones
        
        self.zoom_level_positions = {'l1':None, 'r1':None, 'l2':None, 'r2':None, 'lm':None, 'rm':None}
        self.logerror("autocamera_initialized")
        
    def logerror(self, msg, debug = False):
        if self.DEBUG or debug:
            rospy.logerr(msg)
            
    def dotproduct(self, v1, v2):
        return sum((a*b) for a, b in zip(v1, v2))
    
    def length(self, v):
        return math.sqrt(dotproduct(v, v))
    
    def angle(self, v1, v2):
        return math.acos(dotproduct(v1, v2) / (length(v1) * length(v2)))
      
    def column(self, matrix, i):
        return [row[i] for row in matrix]
    
    def find_rotation_matrix_between_two_vectors(self, a,b):
        a = numpy.array(a).reshape(1,3)[0].tolist()
        b = numpy.array(b).reshape(1,3)[0].tolist()
        
        vector_orig = a / norm(a)
        vector_fin = b / norm(b)
                     
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
        
        
    def extract_positions(self, joint, arm_name, joint_kin=None):
        
        arm_name = arm_name.lower()
        
        if arm_name=="ecm": joint_kin = self.ecm_kin
        elif arm_name =="psm1" : joint_kin = self.psm1_kin
        elif arm_name =="psm2" : joint_kin = self.psm2_kin
                
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
                
    def add_marker(self, pose, name, color=[1,0,1], type=Marker.SPHERE, scale = [.02,.02,.02], points=None, frame = "world"):
        vis_pub = rospy.Publisher(name, Marker, queue_size=10)
        marker = Marker()
        marker.header.frame_id = frame
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
            r = self.find_rotation_matrix_between_two_vectors([1,0,0], [0,0,1])
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
        
    
    def point_towards_midpoint(self, clean_joints, psm1_pos, psm2_pos, key_hole,ecm_pose, cam_info):
        mid_point = (psm1_pos + psm2_pos)/2
#         diff = clean_joints['psm1'].position[2] - clean_joints['psm2'].position[2]
#         if diff > 0:
#             mid_point = (psm1_pos * (1+numpy.abs(diff)/1) + psm2_pos)/2
#         elif diff < 0:
#             mid_point = (psm1_pos + psm2_pos * (1+numpy.abs(diff)/1) )/2
#         else:
#             mid_point = (psm1_pos + psm2_pos)/2
#             
#         l1,l2,lm, r1,r2,rm = self.find_2d_tool_coordinates_in_3d(cam_info, clean_joints)
        
#         if self.last_midpoint == None:
#             self.last_midpoint = mid_point

        
#         if numpy.linalg.norm(mid_point-self.last_midpoint) <  self.pan_tilt_deadzone_radius:
#             mid_point = self.last_midpoint
#         self.logerror("Distance is " + numpy.linalg.norm(mid_point-self.last_midpoint).__str__(), debug=True)
#         mid_point = ecm_pose[0:3,3] - numpy.array([0,0,.01]).reshape(3,1)
        self.add_marker(PoseConv.to_homo_mat([mid_point, [0,0,0]]), '/marker_subscriber',color=[1,0,0], scale=[0.047/5,0.047/5,0.047/5])
        self.add_marker(PoseConv.to_homo_mat([key_hole,[0,0,0]]), '/keyhole_subscriber',[0,0,1])
        self.add_marker(ecm_pose, '/current_ecm_pose', [1,0,0], Marker.ARROW, scale=[.1,.005,.005])
        temp = clean_joints['ecm'].position
        b,_ = self.ecm_kin.FK([temp[0],temp[1],.14,temp[3]])
        # find the equation of the line that goes through the key_hole and the 
        # mid_point
        ab_vector = (mid_point-key_hole)
        ecm_current_direction = b-key_hole 
        self.add_marker(ecm_pose, '/midpoint_to_keyhole', [0,1,1], type=Marker.LINE_LIST, scale = [0.005, 0.005, 0.005], points=[b, key_hole])
        
        self.add_marker(PoseConv.to_homo_mat([ab_vector,[0,0,0]]), '/ab_vector',[0,1,0], type=Marker.ARROW)
        r = self.find_rotation_matrix_between_two_vectors(ecm_current_direction, ab_vector)
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
        self.add_marker(ecm_pose, '/target_ecm_pose', [0,0,1], Marker.ARROW, scale=[.1,.005,.005])
        output_msg = clean_joints['ecm']
        
        try:
            p = self.ecm_kin.inverse(ecm_pose)
        except Exception as e:
            rospy.logerr('error')
        if p != None:  
            p[3] = 0
            output_msg.position = p
        else:
            print("Autocamera Inverse Failure ")
        
#         self.last_midpoint = mid_point
        return output_msg
    
    def find_2d_tool_coordinates_in_3d(self, cam_info, clean_joints):
        if cam_info != None:
            psm1_kin_to_wrist = KDLKinematics(self.psm1_robot, self.psm1_robot.links[0].name, self.psm1_robot.links[-5].name)
            T1W = psm1_kin_to_wrist.forward(clean_joints['psm1'].position)
            
            psm2_kin_to_wrist = KDLKinematics(self.psm2_robot, self.psm2_robot.links[0].name, self.psm2_robot.links[-5].name)
            T2W = psm2_kin_to_wrist.forward(clean_joints['psm2'].position)
            
            TEW = self.ecm_kin.forward(clean_joints['ecm'].position)
            TEW_inv = numpy.linalg.inv(TEW)
            T1W_inv = numpy.linalg.inv(T1W)
            T2W_inv = numpy.linalg.inv(T2W)
            
            mid_point = (T1W[0:4,3] + T2W[0:4,3])/2
            p1 = T1W[0:4,3]
            p2 = T2W[0:4,3]
            
            T2E = TEW_inv * T2W
    
    #         ig = image_geometry.PinholeCameraModel()
            ig = image_geometry.StereoCameraModel()
            
            ig.fromCameraInfo(cam_info['right'], cam_info['left'])
            
            # Format in fakecam.launch:  x y z  yaw pitch roll [fixed-axis rotations: x(roll),y(pitch),z(yaw)]
            # Format for PoseConv.to_homo_mat:  (x,y,z)  (roll, pitch, yaw) [fixed-axis rotations: x(roll),y(pitch),z(yaw)]
            r = PoseConv.to_homo_mat( [ (0.0, 0.0, 0.0), (0.0, 0.0, 1.57079632679) ])
            r_inv = numpy.linalg.inv(r);
            
#             r = numpy.linalg.inv(r)
            self.logerror( r.__str__())
            
#             rotate_vector = lambda x: (r * numpy.array([ [x[0]], [x[1]], [x[2]], [1] ]) )[0:3,3]
             
            l1, r1 = ig.project3dToPixel( ( r_inv * TEW_inv * T1W )[0:3,3]) # tool1 left and right pixel positions
            l2, r2 = ig.project3dToPixel( ( r_inv * TEW_inv * T2W )[0:3,3]) # tool2 left and right pixel positions
            lm, rm = ig.project3dToPixel( ( r_inv * TEW_inv * mid_point)[0:3,0]) # midpoint left and right pixel positions
    #         add_100 = lambda x : (x[0] *.5 + cam_info.width/2, x[1])
    #         l1 = add_100(l1)
    #         l2 = add_100(l2)
    #         lm = add_100(lm)
    
            self.zoom_level_positions = {'l1':l1, 'r1':r1, 'l2':l2, 'r2':r2, 'lm':lm, 'rm':rm}    

            test1_l, test1_r = ig.project3dToPixel( [1,0,0])
            test2_l, test2_r = ig.project3dToPixel( [0,0,1])
            self.logerror('\ntest1_l = ' + test1_l.__str__() + '\ntest2_l = ' + test2_l.__str__() )
            mp = ( int(l1[0]+l2[0])/2, int(l1[1] + l2[1])/2)
            
        return l1,l2,lm, r1,r2,rm   
    
    def zoom_fitness(self, cam_info, mid_point, inner_margin, deadzone_margin, tool_point):
        x = cam_info.width; y = cam_info.height
    #     mid_point = [x/2, y/2]
        
        # if tool in inner zone
        if abs(tool_point[0]-mid_point[0]) <= inner_margin * x/2 and abs(tool_point[1] - mid_point[1]) < inner_margin * y/2:
            r = inner_margin  - max([abs(tool_point[0]-mid_point[0])/(x/2),abs(tool_point[1] - mid_point[1])/(y/2)])
            return r
        # if tool in deadzone
        elif abs(tool_point[0]-mid_point[0]) <= deadzone_margin * x/2 and abs(tool_point[1] - mid_point[1]) < deadzone_margin * y/2:
            return 0
        #if tool in outer zone
        elif abs(tool_point[0]-mid_point[0]) <= x/2 and abs(tool_point[1] - mid_point[1]) <  y/2:
            return -min( [ abs(min([abs(tool_point[0] - x), tool_point[0]])/(x/2) - deadzone_margin),  abs(min([abs(tool_point[1] - y), tool_point[1]])/(y/2) - deadzone_margin)])
        else:
            return -.1
        
    # radius is a percentage of the width of the screen
    def zoom_fitness2(self, cam_info, mid_point, tool_point, tool_point2, radius, deadzone_radius):
        r = radius * cam_info.width # r is in pixels
        dr = deadzone_radius * cam_info.width # dr is in pixels
        
        tool_in_view = lambda tool, safespace : \
        tool[0] > safespace or tool[1] > safespace or tool_point[0] < (cam_info.width-safespace) or \
        tool[1] < (cam_info.height-safespace) 
        dist = lambda a,b : norm( [i-j for i,j in zip(a,b)] )
    
        self.logerror(dist(tool_point, tool_point2))
        now = time.time()
        zoom_time_threshold = .5
        
        tools_are_stationary = False
        
        if self.tool_timer['psm1_stationary_duration'] > zoom_time_threshold and self.tool_timer['psm2_stationary_duration'] > zoom_time_threshold:
            tools_are_stationary = True     
        
        # Inner zone
        if dist(tool_point, mid_point) < abs(r): # the tool's distance from the mid_point < r
            # return positive value
            if self.zones_times['inner_zone'] > 0:
                if (now - self.zones_times['inner_zone'] > zoom_time_threshold) and tools_are_stationary:
                    return 0.0005 # in meters
            else:
                self.zones_times['inner_zone'] = time.time()
                self.zones_times['outer_zone'] = 0
        # Outer zone 
        elif dist(tool_point, mid_point) > abs(r + dr): #  the tool's distance from the mid_point < r
            # return a negative value
            if self.zones_times['outer_zone'] > 0:
                if (now - self.zones_times['outer_zone']) > zoom_time_threshold and tools_are_stationary:
                    return -0.0005 # in meters
            else:
                self.zones_times['outer_zone'] = time.time()
                self.midpoint_time = time.time()
                self.zones_times['inner_zone'] = 0
                
#         elif not tool_in_view(tool_point, 20) or not tool_in_view(tool_point2, 20):
#             return -0.001
        else: # Dead zone
            self.zones_times['outer_zone'] = 0
            self.zones_times['inner_zone'] = 0
            return 0
        return 0
    
    
    def unrectify_point(self, point, camera):
        left_ray = camera.left.projectPixelTo3dRay(point)
        
        t_vec = [0,0,0]
        cv2.Rodrigues( camera.left.R)
    
    
    def get_2d_point_from_3d_point_relative_to_world_rf(self, cam_info, TEW_inv, point):
        b = numpy.matrix( [ [-1, 0, 0], [0,1,0], [0,0,-1]])
    #     point[0:3]  = b * point[0:3]
        
        
        P = numpy.array(cam_info.P).reshape(3,4)
        m = TEW_inv * point
        u,v,w = P * m
        x = u/w
        y = v/w  
        Width = 640; Height = 480
        x = x * .5 + .5 * Width;
        y = y *.5 + .5 * Height
        return ( x,y )
                 
    def find_zoom_level(self, msg, cam_info, clean_joints):
        if cam_info != None:
            psm1_kin_to_wrist = KDLKinematics(self.psm1_robot, self.psm1_robot.links[0].name, self.psm1_robot.links[-1].name)
            T1W = psm1_kin_to_wrist.forward(clean_joints['psm1'].position)
            
            psm2_kin_to_wrist = KDLKinematics(self.psm2_robot, self.psm2_robot.links[0].name, self.psm2_robot.links[-1].name)
            T2W = psm2_kin_to_wrist.forward(clean_joints['psm2'].position)
            
            TEW = self.ecm_kin.forward(clean_joints['ecm'].position)
            TEW_inv = numpy.linalg.inv(TEW)
            T1W_inv = numpy.linalg.inv(T1W)
            T2W_inv = numpy.linalg.inv(T2W)
            
            mid_point = (T1W[0:4,3] + T2W[0:4,3])/2
            p1 = T1W[0:4,3]
            p2 = T2W[0:4,3]
            
            T2E = TEW_inv * T2W
    
    #         ig = image_geometry.PinholeCameraModel()
            ig = image_geometry.StereoCameraModel()
            
            ig.fromCameraInfo(cam_info['right'], cam_info['left'])
            
            # Format in fakecam.launch:  x y z  yaw pitch roll [fixed-axis rotations: x(roll),y(pitch),z(yaw)]
            # Format for PoseConv.to_homo_mat:  (x,y,z)  (roll, pitch, yaw) [fixed-axis rotations: x(roll),y(pitch),z(yaw)]
            r = PoseConv.to_homo_mat( [ (0.0, 0.0, 0.0), (0.0, 0.0, 1.57079632679) ])
            r_inv = numpy.linalg.inv(r);
            
#             r = numpy.linalg.inv(r)
            self.logerror( r.__str__())
            
#             rotate_vector = lambda x: (r * numpy.array([ [x[0]], [x[1]], [x[2]], [1] ]) )[0:3,3]
             
            self.add_marker(T2W, '/left_arm', scale=[.002,.002,.002])
            
            
            l1, r1 = ig.project3dToPixel( ( r_inv * TEW_inv * T1W )[0:3,3]) # tool1 left and right pixel positions
            l2, r2 = ig.project3dToPixel( ( r_inv * TEW_inv * T2W )[0:3,3]) # tool2 left and right pixel positions
            lm, rm = ig.project3dToPixel( ( r_inv * TEW_inv * mid_point)[0:3,0]) # midpoint left and right pixel positions
    #         add_100 = lambda x : (x[0] *.5 + cam_info.width/2, x[1])
    #         l1 = add_100(l1)
    #         l2 = add_100(l2)
    #         lm = add_100(lm)
    
            self.zoom_level_positions = {'l1':l1, 'r1':r1, 'l2':l2, 'r2':r2, 'lm':lm, 'rm':rm}    

            test1_l, test1_r = ig.project3dToPixel( [1,0,0])
            test2_l, test2_r = ig.project3dToPixel( [0,0,1])
            self.logerror('\ntest1_l = ' + test1_l.__str__() + '\ntest2_l = ' + test2_l.__str__() )
    #         logerror('xm=%f,'%lm[0] +  'ym=%f'%lm[1])
            
            msg.position[3] = 0
#             zoom_percentage = self.zoom_fitness(cam_info=cam_info['left'], mid_point=lm, inner_margin=.20,
#                                             deadzone_margin= .70, tool_point= l1)
             
            mp = ( int(l1[0]+l2[0])/2, int(l1[1] + l2[1])/2)
            zoom_percentage = self.zoom_fitness2(cam_info['left'], mid_point=mp, tool_point=l1, 
                                            tool_point2=l2, radius=self.zoom_innerzone_radius, deadzone_radius=self.zoom_deadzone_radius)
            
            print("zoom_percentage = {} ".format(zoom_percentage))
            msg.position[2] =  msg.position[2] + zoom_percentage 
            if msg.position[2] < 0 : # minimum 0
                msg.position[2] = 0.00
            elif msg.position[2] > .15: # maximum .23
                msg.position[2] = .15
        return msg   
    
    
    def track_tool_times(self, joints):
        if self.tool_timer['last_psm1_pos'] is None:
            self.tool_timer['last_psm1_pos'] = joints['psm1'].position
            self.tool_timer['psm1_stay_start_time'] = time.time()
        else:
            # If the tool has moved
            if not (numpy.linalg.norm( numpy.array(self.tool_timer['last_psm1_pos'])- numpy.array(joints['psm1'].position)) <0.002):
                self.tool_timer['psm1_stay_start_time'] = time.time()
                self.tool_timer['psm1_stationary_duration'] = 0
            else: # If the tool hasn't moved
                self.tool_timer['psm1_stationary_duration'] = time.time() - self.tool_timer['psm1_stay_start_time']
            self.tool_timer['last_psm1_pos'] = joints['psm1'].position
                
        if self.tool_timer['last_psm2_pos'] is None:
            self.tool_timer['last_psm2_pos'] = joints['psm2'].position
            self.tool_timer['psm2_stay_start_time'] = time.time()
        else:
            # If the tool has moved
            print('some number = {}\n'.format(numpy.linalg.norm(numpy.array(self.tool_timer['last_psm2_pos'])- numpy.array(joints['psm2'].position))))
            if not (numpy.linalg.norm(numpy.array(self.tool_timer['last_psm2_pos'])- numpy.array(joints['psm2'].position)) <0.002):
                self.tool_timer['psm2_stay_start_time'] = time.time()
                self.tool_timer['psm2_stationary_duration'] = 0
            else: # If the tool hasn't moved
                self.tool_timer['psm2_stationary_duration'] = time.time() - self.tool_timer['psm2_stay_start_time']
            self.tool_timer['last_psm2_pos'] = joints['psm2'].position
    
    def compute_viewangle(self, joint, cam_info):
        kinematics = lambda name: self.psm1_kin if name == 'psm1' else self.psm2_kin if name == 'psm2' else self.ecm_kin 
        clean_joints = {}
        try:
            joint_names = joint.keys()
            for j in joint_names:
                clean_joints[j] = self.extract_positions(joint[j], j, kinematics(j))
        
            key_hole, _ = self.ecm_kin.FK([0,0,0,0]) # The position of the keyhole, is the end-effector's
            psm1_pos,_ = self.psm1_kin.FK(clean_joints['psm1'].position)
            psm2_pos,_ = self.psm2_kin.FK(clean_joints['psm2'].position)
            psm1_pose = self.psm1_kin.forward(clean_joints['psm1'].position)
            ecm_pose = self.ecm_kin.forward(clean_joints['ecm'].position)
        
        
        except Exception as e:
            rospy.logerr(e.message)
            output_msg = joint['ecm']
    #         output_msg.name = ['outer_yaw', 'outer_pitch', 'insertion', 'outer_roll']
    #         output_msg.position = [joint['ecm'].position[x] for x in [0,1,5,6]]
            return output_msg
        
        output_msg = clean_joints['ecm']
        
        gripper= max( [ abs(joint['psm1'].position[-1]), abs(joint['psm2'].position[-1])] ) < math.pi/8
    #     rospy.logerr('psm1 gripper = ' + joint['psm1'].position[-1].__str__() + 'gripper = ' + gripper.__str__())
        
        # Track when the tools are stationary
        self.track_tool_times(clean_joints)
        
        if gripper == gripper or gripper != gripper: # luke was here
            output_msg = self.point_towards_midpoint(clean_joints, psm1_pos, psm2_pos, key_hole, ecm_pose, cam_info)
#             output_msg.position =list( numpy.array(output_msg.position) + ( -numpy.array(output_msg.position)+ numpy.array(goal_joints.position)) *.0001)
            output_msg = self.find_zoom_level(output_msg, cam_info, clean_joints)
            pass
        
        if len(output_msg.name) > 4:
            output_msg.name = ['outer_yaw', 'outer_pitch', 'insertion', 'outer_roll']
        if len(output_msg.position) >= 7:
            output_msg.position = [output_msg.position[x] for x in [0,1,5,6]]
            
            
        self.logerror(output_msg.__str__())
        return output_msg
    
    