# imgdiff 
Tool for checking the binary equivalence of two built images.

The tool currently accepts two .tar.bz2 images, or two directories where such
images have already been unpacked.  If two .tar.bz2 files are given, the files
will be unpacked into temporary directories before the compare is done.

The tool builds a list of every file in each image. The SHA-256 checksum is
generated for each file to compare its binary equivalence to the corresponding
file in the other image. If there is no corresponding file in the other image,
the file is reported missing. If a missmatch is found, optionally the
'diffoscope' tool can be run on the differing files to generate a deeper
analysis of why the files differ.

Please see the usage description by running imgdiff.py -h for additional
features.
