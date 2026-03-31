project('gesture_detection_postprocess', 'cpp',
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

shared_library('palm_detection_postprocess',
  'palm_detection_postprocess.cpp',
  dependencies : [postprocess_dep],
  gnu_symbol_visibility : 'default',
  install : true,
  install_dir : so_install_dir,
)

shared_library('palm_croppers',
  'palm_croppers.cpp',
  dependencies : [postprocess_dep],
  gnu_symbol_visibility : 'default',
  install : true,
  install_dir : so_install_dir,
)

hand_warp_deps = [postprocess_dep, gst_video_dep]
if opencv_dep.found()
  hand_warp_deps += [opencv_dep]
endif
if zlib_dep.found()
  hand_warp_deps += [zlib_dep]
endif

shared_library('hand_affine_warp',
  'hand_affine_warp.cpp',
  dependencies : hand_warp_deps,
  gnu_symbol_visibility : 'default',
  install : true,
  install_dir : so_install_dir,
)

shared_library('hand_landmark_postprocess',
  'hand_landmark_postprocess.cpp',
  dependencies : [postprocess_dep],
  gnu_symbol_visibility : 'default',
  install : true,
  install_dir : so_install_dir,
)

shared_library('gesture_classification',
  'gesture_classification.cpp',
  dependencies : [postprocess_dep],
  gnu_symbol_visibility : 'default',
  install : true,
  install_dir : so_install_dir,
)
