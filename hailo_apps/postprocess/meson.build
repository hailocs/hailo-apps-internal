project('hailo-apps', 'c', 'cpp',
        version : '25-12',
        default_options : [ 'warning_level=1',
                            'buildtype=release',
                            'c_std=c11', 'cpp_std=c++17',
                            'c_args=-Wno-psabi',
                            'cpp_args=-Wno-psabi -Wno-class-memaccess -Wno-deprecated-declarations']
       )

postprocess_dep = dependency('hailo-tappas-core', version : '>=3.30.0', required : false)

if not postprocess_dep.found()
    postprocess_dep = dependency('hailo_tappas', version : '>=3.30.0', required : false)
endif

zlib_dep = dependency('zlib', required : false)

# Try to find OpenCV4 for static linking
# Option 1: Prefer static OpenCV (if available)
# Set static: true to prefer static libraries
opencv_dep_static = dependency('opencv4', required : false, static : true)

# Option 2: If static OpenCV is not available, fall back to dynamic
# This ensures we can still build even if static libraries aren't installed
if opencv_dep_static.found()
    opencv_dep = opencv_dep_static
else
    opencv_dep = dependency('opencv4', required : false)
    if opencv_dep.found()
        message('⚠️  Static OpenCV not found, using dynamic OpenCV from TAPPAS')
    endif
endif

# Option 3: If you want to force static linking and fail if not available, use:
# opencv_dep = dependency('opencv4', required : true, static : true)

if postprocess_dep.found()
    rapidjson_inc_dir = postprocess_dep.get_variable(pkgconfig: 'rapidjson_includedir', default_value: '')
    rapidjson_inc = include_directories(rapidjson_inc_dir, is_system: true)

    subdir('cpp')
else
    message('⚠️  No Hailo TAPPAS dependencies found — skipping C++ postprocess build.')
endif
