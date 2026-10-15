"""RGB-only worker wiring; synthetic frames, mocked models, no real face data."""
from contextlib import ExitStack
import hashlib,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import numpy as np
try:import cv2
except ImportError:cv2=None
import face_engine as engine

@unittest.skipUnless(cv2 is not None and sys.platform=='linux','Target OpenCV; all devices/models mocked')
class RGBCaptureTests(unittest.TestCase):
 def run_worker(self,operation='verify',reference=None,faces=1,bad_frame=False):
  timer=[1000.]
  def clock():timer[0]+=.01;return timer[0]
  def sleep(seconds):timer[0]+=seconds
  yy,xx=np.indices((480,640))
  image=np.stack((xx%256,yy%256,(xx+yy)%256),axis=-1).astype(np.uint8)
  camera=Mock();camera.isOpened.return_value=True
  camera.read.return_value=(False,None) if bad_frame else (True,image)
  detector=Mock()
  face=np.array([150,80,150,180,185,135,255,135,220,175,195,210,245,210,.99],np.float32)
  detector.detect.return_value=(None,np.array([face]*faces) if faces else None)
  recognizer=Mock();recognizer.alignCrop.return_value=np.zeros((112,112,3),np.uint8)
  recognizer.feature.return_value=np.array([[1.]+[0.]*127],np.float32)
  owner=self
  class Preview:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def publish(self,frame):owner.preview=frame.copy()
   def close(self):pass
  with tempfile.TemporaryDirectory() as folder,ExitStack() as stack:
   directory=Path(folder);(directory/'detector.onnx').write_bytes(b'synthetic model')
   models={'detector.onnx':hashlib.sha256(b'synthetic model').hexdigest()}
   real_open=os.open
   stack.enter_context(patch.dict(engine.MODELS,models,clear=True))
   stack.enter_context(patch.dict(sys.modules,{'d2_camera':None,'face_pad':None}))
   stack.enter_context(patch('face_engine.rgb_device',return_value='/dev/mock-d2-rgb'))
   create=stack.enter_context(patch('face_rgb_stream.RGBCamera',return_value=camera))
   stack.enter_context(patch('face_engine.os.open',side_effect=lambda p,f,m:real_open(directory/'lease',f,m)))
   stack.enter_context(patch('face_engine.time.monotonic',clock))
   stack.enter_context(patch('face_engine.time.sleep',sleep))
   stack.enter_context(patch('face_engine.PreviewPublisher',Preview))
   stack.enter_context(patch('cv2.FaceDetectorYN_create',return_value=detector))
   stack.enter_context(patch('cv2.FaceRecognizerSF_create',return_value=recognizer))
   stack.enter_context(patch('cv2.Laplacian',return_value=np.array([[0,100],[100,0]])))
   if bad_frame:
    with self.assertRaisesRegex(RuntimeError,'读取中断'):engine.capture(operation,directory,{'embedding':[1.]+[0.]*127})
    result=None
   elif operation=='enroll' and not faces:
    with self.assertRaisesRegex(RuntimeError,'未更改原资料'):engine.capture(operation,directory,{})
    result=None
   else:result=engine.capture(operation,directory,{'embedding':reference or [1.]+[0.]*127})
   create.assert_called_once_with('/dev/mock-d2-rgb',cv2.CAP_V4L2)
   camera.release.assert_called_once()
   self.assertFalse(list(directory.glob('screen_face*')))
   return result,recognizer.feature.call_count,image

 def test_rgb_matching_succeeds_without_any_depth_or_ir_modules(self):
  result,calls,image=self.run_worker()
  self.assertTrue(result['matched']);self.assertGreaterEqual(result['samples'],5)
  self.assertNotIn('pad_passed',result);self.assertNotIn('policy',result)
  self.assertGreaterEqual(calls,5)
  np.testing.assert_array_equal(self.preview,image)
  self.assertFalse(np.array_equal(self.preview[:,:,0],self.preview[:,:,1]))

 def test_wrong_identity_remains_locked(self):
  result,_,_=self.run_worker(reference=[0.,1.]+[0.]*126)
  self.assertFalse(result['matched']);self.assertEqual(result['samples'],0)

 def test_missing_or_multiple_faces_do_not_generate_identity_samples(self):
  for count in (0,2):
   result,calls,_=self.run_worker(faces=count)
   self.assertFalse(result['matched']);self.assertEqual(calls,0)

 def test_enrollment_only_returns_temporary_rgb_features(self):
  result,calls,_=self.run_worker(operation='enroll')
  self.assertGreaterEqual(result['samples'],5);self.assertGreaterEqual(calls,5)
  self.assertEqual(len(result['embedding']),128)
  self.assertAlmostEqual(np.linalg.norm(result['embedding']),1.)

 def test_enrollment_without_a_face_cannot_write_a_template(self):
  self.run_worker(operation='enroll',faces=0)

 def test_camera_failure_releases_rgb_lease_and_does_not_return_features(self):
  self.run_worker(bad_frame=True)

if __name__=='__main__':unittest.main()
