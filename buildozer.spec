[app]
title = HyperOS Icon Packer
package.name = hyperosiconpacker
package.domain = com.tools

source.dir = .
source.include_exts = py,png,kv,atlas,xml

version = 1.0

requirements = python3,kivy==2.3.1,pillow,android

orientation = portrait
fullscreen = 0

android.permissions = READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE,MANAGE_EXTERNAL_STORAGE
android.api = 33
android.minapi = 26
android.ndk = 25b
android.archs = arm64-v8a, armeabi-v7a

android.allow_backup = True

[buildozer]
log_level = 2
warn_on_root = 1
