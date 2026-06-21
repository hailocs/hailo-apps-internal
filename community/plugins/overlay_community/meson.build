project('hailooverlay_community', 'cpp',
  version : '1.0.0',
  default_options : [
    'cpp_std=c++17',
    'warning_level=1',
    'buildtype=release',
  ]
)

# hailo-tappas-core provides hailo_objects.hpp / hailomat.hpp / gst_hailo_meta.hpp /
# image.hpp and the rest of the TAPPAS postprocess headers this element draws with.
postprocess_dep = dependency('hailo-apps-core', version : '>=3.30.0', required : false)
if not postprocess_dep.found()
  postprocess_dep = dependency('hailo-tappas-core', version : '>=3.30.0', required : false)
endif
if not postprocess_dep.found()
  postprocess_dep = dependency('hailo_tappas', version : '>=3.30.0', required : true)
endif

gst_dep       = dependency('gstreamer-1.0', required : true)
gst_base_dep  = dependency('gstreamer-base-1.0', required : true)
gst_video_dep = dependency('gstreamer-video-1.0', required : true)

# The overlay's styling/sprite config is yaml-cpp driven (style_config.hpp /
# sprite_cache.hpp). Required: install libyaml-cpp-dev before building (see README).
yaml_cpp_dep = dependency('yaml-cpp', required : true)

opencv_dep = dependency('opencv4', required : false)
if not opencv_dep.found()
  opencv_dep = dependency('opencv', required : true)
endif

add_project_arguments('-Wno-psabi', '-Wno-class-memaccess', '-Wno-deprecated-declarations', language : 'cpp')

# --- TAPPAS version → -DHAILO_TAPPAS_VER (major*100+minor) -------------------
# hailomat_compat.hpp bridges the HailoMat drawing API across TAPPAS versions
# using this define. 0 means unknown (the shim falls back to the newest API).
tappas_ver_int = 0
pkg_name = 'hailo-apps-core'
pkg_version_result = run_command('pkg-config', '--modversion', pkg_name, check : false)
if pkg_version_result.returncode() != 0
  pkg_name = 'hailo-tappas-core'
  pkg_version_result = run_command('pkg-config', '--modversion', pkg_name, check : false)
endif
if pkg_version_result.returncode() != 0
  pkg_name = 'hailo_tappas'
  pkg_version_result = run_command('pkg-config', '--modversion', pkg_name, check : false)
endif
if pkg_version_result.returncode() == 0
  version_parts = pkg_version_result.stdout().strip().split('.')
  if version_parts.length() >= 2
    tappas_ver_int = version_parts[0].to_int() * 100 + version_parts[1].to_int()
  endif
endif
message('TAPPAS version int: @0@'.format(tappas_ver_int))

overlay_deps = [postprocess_dep, gst_dep, gst_base_dep, gst_video_dep, yaml_cpp_dep, opencv_dep]

# TAPPAS 5.3 moved the HailoMat geometry symbols (width/height/native_width/
# native_height) into libhailo_opencv_utils.so. Link it when present; meson's
# pkg-config dep resolution otherwise drops -lhailo_opencv_utils and the element
# fails with undefined references. Absent on TAPPAS < 5.3 (symbols are inline).
cpp_compiler = meson.get_compiler('cpp')
libhailo_opencv_utils_dep = cpp_compiler.find_library('hailo_opencv_utils', required : false)
if libhailo_opencv_utils_dep.found()
  overlay_deps += libhailo_opencv_utils_dep
endif

# Install into the system GStreamer plugin dir so gst-inspect / pipelines discover it.
gst_plugins_dir = '/usr/lib/gstreamer-1.0'
gst_plugins_dir_result = run_command('pkg-config', '--variable=pluginsdir', 'gstreamer-1.0', check : false)
if gst_plugins_dir_result.returncode() == 0 and gst_plugins_dir_result.stdout().strip() != ''
  gst_plugins_dir = gst_plugins_dir_result.stdout().strip()
endif
message('GStreamer plugin install dir: @0@'.format(gst_plugins_dir))

shared_library('gsthailooverlay_community',
  ['gsthailooverlay_community.cpp',
   'overlay.cpp'],
  include_directories : include_directories('.'),
  dependencies : overlay_deps,
  cpp_args : ['-DPACKAGE="hailooverlay_community"', '-DHAILO_TAPPAS_VER=' + tappas_ver_int.to_string()],
  gnu_symbol_visibility : 'default',
  install : true,
  install_dir : gst_plugins_dir,
)
