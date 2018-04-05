#!/usr/bin/env python3

import os
import stat
import sys
import argparse
import subprocess
import hashlib
import tempfile
import tarfile

class Image(object):
    def __init__(self, image=None, root=None, files=None, tmp_dir=None):
        super(Image, self).__init__()
        self.image = image
        self.root = root    
        self.files = files
        self.tmp_dir = tmp_dir
        
def sha256sum(filename,block_size=65536, retry=True): # Default block_size is 64k
    sha256 = hashlib.sha256()
    try:
        with open(filename, 'rb') as f:
            while True:
                data = f.read(block_size)
                if not data:
                    break
                sha256.update(data)
    except PermissionError:
        if retry:
            os.chmod(filename, os.stat(filename).st_mode | stat.S_IRUSR) # Add u+r permission
            return sha256sum(filename, retry=False)
        else:
            raise PermissionError
    return sha256.hexdigest()

def get_contents(top_dir, sorted=False):
    top_dir = top_dir.rstrip('/')
    
    file_dict = {}

    for root, dirs, files in os.walk(top_dir):
        if sorted:
            dirs.sort() # Affects recursive traversal order
            files.sort() # Affects file inspection order
        for file in files:
            path = os.path.relpath(root,top_dir)
            if not path in file_dict:
                file_dict[path] = {}
            file_dict[path][file] = os.path.join(root, file)
    return file_dict

def main():
    parser = argparse.ArgumentParser(
            description="image and directory binary diff tool")
    parser.add_argument('images', metavar='IMAGE_FILE', nargs=2,
            help='Two images to make binary diff. Each should be a directory or .tar.bz2 image of a build.')
    parser.add_argument('-d', '--diffoscope',
            help='run diffoscope on files that do not match.',
            action='store_true')
    parser.add_argument('-o', '--output-file',
            help='output file to use instead of stdout.')
    parser.add_argument('-s', '--stats',
            help='output statistics about diff', action='store_true')
    parser.add_argument('-r', '--sort',
            help='traverse files in sorted order (easier for human inspection)', action='store_true')

    args = parser.parse_args()

    output_handle = open(args.output_file, 'w') if args.output_file else sys.stdout
    error_handle = output_handle if args.output_file else sys.stderr

    if args.diffoscope:
        try:
            subprocess.run("diffoscope --version", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
        except subprocess.SubprocessError:
            error_handle.write("Please install diffoscope\n")
            sys.exit(1)


    image1 = Image(image=args.images[0])
    image2 = Image(image=args.images[1])

    # Set up the directories to compare
    if os.path.isdir(image1.image): # If image1 is an already unpacked dir
        image1.root = image1.image
    elif tarfile.is_tarfile(image1.image): # If image1 is tar.bz2
        image1.tmp_dir = tempfile.TemporaryDirectory()
        image1.root = image1.tmp_dir.name
        # Unpack the images to temporary directory
        try:
            subprocess.run('tar --atime-preserve -xjsf %s -C %s' % (image1.image, image1.root),
                shell=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        except subprocess.SubprocessError:
            error_handle.write("Error unpacking image: %s" % image1.image)
            sys.exit(1)
    # elif is ext4 partition, mount it    
    
    if os.path.isdir(image2.image): # If image2 is an already unpacked dir
        image2.root = image2.image
    elif tarfile.is_tarfile(image2.image):
        image2.tmp_dir = tempfile.TemporaryDirectory()
        image2.root = image2.tmp_dir.name
        # Unpack the images to temporary directory
        try:
            subprocess.run('tar --atime-preserve -xjpsf %s -C %s' % (image2.image, image2.root),
                shell=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        except subprocess.SubprocessError:
            error_handle.write("Error unpacking image: %s" % image2.image)
            sys.exit(1)
    # elif is ext4 partition, mount it    
    
    image1.files = get_contents(image1.root, args.sort)
    image2.files = get_contents(image2.root, args.sort)

    ret = 0;
    stats = {'match'        : 0,
             'missmatch'    : 0,
             'missing1'     : 0,
             'missing2'     : 0,
             'dir_missing1' : 0,
             'dir_missing2' : 0}
    for dir in image1.files:
        if dir in image2.files:
            # Check all files in image1.files[dir] against files in image2.files[dir]
            for file in image1.files[dir]:
                if file in image2.files[dir]:
                    match = True
                    try:
                        # If either file is a symlink, check that the other is too and that they point to the same target
                        if os.path.islink(image1.files[dir][file]) or os.path.islink(image2.files[dir][file]):
                            if not (os.path.islink(image1.files[dir][file]) and os.path.islink(image2.files[dir][file])):
                                match = False
                            elif os.readlink(image1.files[dir][file]) != os.readlink(image2.files[dir][file]):
                                match = False
                       # Else if it's a normal file, compare checksums
                        elif sha256sum(image1.files[dir][file]) != sha256sum(image2.files[dir][file]):
                            match = False
                    except PermissionError:
                        error_handle.write('Permission Error: cannot compare %s' % os.path.join(dir,file))

                    # If the files matched
                    if match:
                        if args.stats:
                            stats['match'] += 1
                    else:
                        output_handle.write("File Missmatch: '%s' from %s and %s\n" % (os.path.join(dir,file), image1.image, image2.image))
                        if args.stats:
                            stats['missmatch'] += 1
                        ret = 1
                        if args.diffoscope:
                            output_handle.write("diffoscope output:\n")
                            try:
                                output_handle.write(subprocess.run('diffoscope %s %s' % (image1.files[dir][file],image2.files[dir][file]),
                                    shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout.decode('utf-8'))
                            except subprocess.SubprocessError:
                                error_handle.write('Call to diffoscope failed.\n')

                    image2.files[dir].pop(file, None) # So we can check later if anything is left in image2.files[dir]
                else:
                    output_handle.write("Missing File: '%s' from %s not found in %s\n" % (os.path.join(dir,file), image1.image, image2.image))
                    if args.stats:
                        stats['missing1'] += 1
                    ret = 1
            # If there's anything left in image2.files[dir], it wasn't in image1.files[dir]
            for file in image2.files[dir]:
                output_handle.write("Missing File: '%s' from %s not found in %s\n" % (os.path.join(dir,file), image2.image, image1.image))
                if args.stats:
                    stats['missing2'] += 1
                ret = 1
            image2.files.pop(dir, None) # So we can check later if anything is left in image2.files
        else:
            output_handle.write("Missing Directory (with %i files): '%s' from %s not found in %s\n" % (len(image1.files[dir]), dir, image1.image, image2.image))
            if args.stats:
                stats['dir_missing1'] +=1
                stats['missing1'] += len(image1.files[dir])
            ret = 1
    # if there is anything left in image2.files, it wasn't in image1.files
    for dir in image2.files:
        output_handle.write("Missing Directory (with %i files): '%s' from %s not found in %s\n" % (len(image2.files[dir]), dir, image2.image, image1.image))
        if args.stats:
            stats['dir_missing2'] += 1
            stats['missing2'] += len(image2.files[dir])
        ret = 1


    if args.stats:
        file_total = stats['match'] + stats['missmatch'] + stats['missing1'] + stats['missing2']
        missing_total = stats['missing1'] + stats['missing2']
        output_handle.write('----------------------STATS----------------------\n')
        output_handle.write('Total files compared: %i\n' % file_total)
        output_handle.write('Matches: %i (%s)\n' % (stats['match'], '{:.2%}'.format(stats['match']/file_total)))
        output_handle.write('Misses: %i (%s)\n' % (stats['missmatch'], '{:.2%}'.format(stats['missmatch']/file_total)))
        output_handle.write('Missing: %i (%s)\n' % (missing_total, '{:.2%}'.format(missing_total/file_total)))
        output_handle.write('Files from %s missing from %s: %i\n' % (image1.image,image2.image,stats['missing1']))
        output_handle.write('Files from %s missing from %s: %i\n' % (image2.image,image1.image,stats['missing2']))
        output_handle.write('Dirs from %s missing from %s: %i\n' % (image1.image,image2.image,stats['dir_missing1']))
        output_handle.write('Dirs from %s missing from %s: %i\n' % (image2.image,image1.image,stats['dir_missing2']))

    # Close output handle if file
    if output_handle is not sys.stdout:
        output_handle.close()
    # Clean up any temp directories
    if image1.tmp_dir:
        del image1.tmp_dir
    if image2.tmp_dir:
        del image2.tmp_dir

    return ret

if __name__ == '__main__':
    try:
        ret =  main()
    except Exception:
        ret = 1
        import traceback
        traceback.print_exc()
    sys.exit(ret)

