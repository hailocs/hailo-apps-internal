project('face_landmarks_postprocess', 'cpp',
  version : '1.0.0',
  default_options : [
    'cpp_std=c++17',
    'warning_level=1',
    'buildtype=release',
  ]
)

postprocess_dep = dependency('hailo-tappas-core', version : '>=3.30.0', required : true)

opencv_dep = dependency('opencv4', required : false)
if not opencv_dep.found()
  opencv_dep = dependency('opencv', required : true)
endif
gst_video_dep = dependency('gstreamer-video-1.0', required : true)
zlib_dep = dependency('zlib', required : false)

add_project_arguments('-Wno-psabi', '-Wno-class-memaccess', '-Wno-deprecated-declarations', language : 'cpp')

so_install_dir = '/usr/local/hailo/resources/so'

# Landmark postprocess — reshapes model output tensors to HailoMatrix landmarks
shared_library('face_landmarks_postprocess',
  'face_landmarks_postprocess.cpp',
  dependencies : [postprocess_dep],
  gnu_symbol_visibility : 'default',
  install : true,
  install_dir : so_install_dir,
)

# Face mesh alignment — rotation-aware warp using SCRFD eye keypoints.
# Uses OpenCV + GStreamer-Video to warp the cropped frame in place.
align_deps = [postprocess_dep, gst_video_dep, opencv_dep]
if zlib_dep.found()
  align_deps += [zlib_dep]
endif
shared_library('face_mesh_align',
  'face_mesh_align.cpp',
  dependencies : align_deps,
  gnu_symbol_visibility : 'default',
  install : true,
  install_dir : so_install_dir,
)
