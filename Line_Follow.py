#!/usr/bin/env python
import roslib
import sys
import rospy
import cv2 as cv
import numpy as np
from std_msgs.msg import String
from sensor_msgs.msg import CompressedImage
from cv_bridge import CvBridge, CvBridgeError
from dynamic_reconfigure.server import Server
from dynamic_reconfigure.client import Client
from jetracer.cfg import LineFollowConfig
from geometry_msgs.msg import Twist

class image_converter:

  def __init__(self):
    self.camera_name = rospy.get_param("~camera_name","csi_cam_0")
    self.topic_name = rospy.get_param("~topic_name","color_tracking")

    self.bridge = CvBridge()
    rospy.on_shutdown(self.shutdown)
    self.image_sub = rospy.Subscriber(self.camera_name+"/image_raw/compressed",CompressedImage,self.callback)
    self.image_pub = rospy.Publisher(self.topic_name+"/compressed",CompressedImage,queue_size=10)
    self.cmd_pub = rospy.Publisher('/cmd_vel', Twist,queue_size=10)
    self.cmd = Twist()
    self.kp = 0
    self.kd = 0
    self.last_err = 0
    self.Max = 1.5    #angular
    self.switch = False
    self.xy=np.array([(0,0),(0,0)])
    self.drawing = False
    self.setcolor = False;

    self.lower= np.array([110,100,100])
    self.upper= np.array([130,255,255])

    server = Server(LineFollowConfig,self.colorConfig_callback)
    self.client = Client("line_follow", timeout=60)

  def shutdown(self):
    self.cmd_pub.publish(Twist())

  def colorConfig_callback(self, config, level):
    self.lower= np.array([config['Hmin'],config['Smin'],config['Vmin']])
    self.upper= np.array([config['Hmax'],config['Smax'],config['Vmax']])
    self.cmd.linear.x = config['linear']
    self.kp= config['Kp']
    self.kd= config['Kd']
    self.switch = config['start']
    return config

  def onMouse(self,event, x,y,flags,param):
    if event == cv.EVENT_LBUTTONDOWN:
	self.drawing = True
	self.xy[0]=(x,y)
    elif event == cv.EVENT_MOUSEMOVE:
	self.xy[1]=(x,y)
    elif event == cv.EVENT_LBUTTONUP:
	self.drawing = False
	self.setcolor = True


  def callback(self,data):
    try:
      cv_image = self.bridge.compressed_imgmsg_to_cv2(data, "bgr8")
    except CvBridgeError as e:
      print(e)

    if self.setcolor:
      try:
        Roi = cv_image[min(self.xy[:,1]):max(self.xy[:,1]),min(self.xy[:,0]):max(self.xy[:,0])]
        hsv = cv.cvtColor(Roi, cv.COLOR_BGR2HSV)

        H_min=min(hsv[:,:,0][0])
        S_min=min(hsv[:,:,1][0])
        V_min=min(hsv[:,:,2][0])
        H_max=max(hsv[:,:,0][0])
        S_max=max(hsv[:,:,1][0])
        V_max=max(hsv[:,:,2][0])

        # HSV range adjustment
        if H_max + 5 > 255:H_max = 255
        else:H_max += 5
        if H_min - 5 < 0:H_min = 0
        else:H_min -= 5
        if S_min - 20 < 0:S_min = 0
        else:S_min -= 20
        if V_min - 20 < 0:V_min = 0
        else:V_min -= 20
        S_max = 255;V_max = 255

	config = {'Hmin': H_min, 'Hmax': H_max,
		'Smin': S_min, 'Smax': S_max,
		'Vmin': V_min, 'Vmax': V_max}
	self.client.update_configuration(config)

        self.lower=np.array([H_min,S_min,V_min])
        self.upper=np.array([H_max,S_max,V_max])
      except:
	print("The color cannot be selected normally")
      self.setcolor = False

    else:
      height, width = cv_image.shape[:2]
      # Convert BGR to HSV
      hsv = cv.cvtColor(cv_image, cv.COLOR_BGR2HSV)
      # Threshold the HSV image to get only blue colors
      mask = cv.inRange(hsv, self.lower, self.upper)
      mask[0:int(height / 2), 0:width] = 0

      # Bitwise-AND mask and original image
      res = cv.bitwise_and(cv_image,cv_image, mask= mask)
	
      # Convert the image to grayscale
      gray_img = cv.cvtColor(res, cv.COLOR_RGB2GRAY)

      # Image binarization operation
      ret, binary = cv.threshold(gray_img, 10, 255, cv.THRESH_BINARY)

      contours, hierarchy = cv.findContours(binary, cv.RETR_EXTERNAL, cv.CHAIN_APPROX_SIMPLE)

      if len(contours) != 0:
	areas = [];
	for c in contours: areas.append(cv.contourArea(c))
        cnt = contours[areas.index(max(areas))]
	if(cv.contourArea(cnt) > 50):
            rect = cv.minAreaRect(cnt)
            box = cv.boxPoints(rect)
            box = np.int0(box)
            cv.drawContours(cv_image, [box], 0, (0, 255, 0), 2)

	    (cx,cy),radius = cv.minEnclosingCircle(cnt)
	    x = int(cx)
	    y = int(cy)
            cv.line(cv_image,(x-10,y),(x+10,y),(255,0,0),2)
            cv.line(cv_image,(x,y-10),(x,y+10),(255,0,0),2)
            cv.line(cv_image,(width/2,height),(x,y),(255,0,0),2)

            err = (width/2 - x)/float((height - y))
	
            self.cmd.angular.z = (self.kp*err + self.kd*(err - self.last_err))*0.01;
            if(self.cmd.angular.z > self.Max):self.cmd.angular.z = self.Max
            elif(self.cmd.angular.z < -self.Max):self.cmd.angular.z = -self.Max

            if(self.switch):
	        self.cmd_pub.publish(self.cmd)
            else:
	        self.cmd_pub.publish(Twist())
	else:
	    self.cmd_pub.publish(Twist())
      else:
	  self.cmd_pub.publish(Twist())

      #cv.imshow("Color mask", mask)
      cv.imshow("Color Tracking", res)

    cv.putText(cv_image, "Upper : "+str(self.upper), (30, 30), cv.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)
    cv.putText(cv_image, "Lower : "+str(self.lower), (30, 50), cv.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 1)


    if(self.drawing):
      cv.rectangle(cv_image,tuple(self.xy[0]),tuple(self.xy[1]),(0,255,0),2)
      cv.line(cv_image, tuple(self.xy[0]), tuple(self.xy[1]), (255, 0, 0), 2)

    cv.imshow("Image window", cv_image)
    cv.setMouseCallback("Image window",self.onMouse)
    cv.waitKey(3)

    try:
      self.image_pub.publish(self.bridge.cv2_to_compressed_imgmsg(cv_image))
    except CvBridgeError as e:
      print(e)

def main(args):
  rospy.init_node('image_converter', anonymous=True)
  ic = image_converter()
  try:
    rospy.spin()
  except KeyboardInterrupt:
    print("Shutting down")
  cv.destroyAllWindows()

if __name__ == '__main__':
    main(sys.argv)
