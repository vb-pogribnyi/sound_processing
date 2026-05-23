import math
import numpy as np
import cv2 as cv
from tqdm import tqdm

DEBUG = False

def rotate_vector(vector, angle_degrees):
    x, y = vector
    # Convert degrees to radians because math functions use radians
    theta = math.radians(angle_degrees)
    
    # Apply the rotation formulas
    new_x = x * math.cos(theta) - y * math.sin(theta)
    new_y = x * math.sin(theta) + y * math.cos(theta)
    
    return (new_x, new_y)

class SourceDrawer:
    def __init__(self, mesh, plane_reader, nblades, blade_length, blade_width, blade_thickness):
        self.mesh = mesh
        self.plane_reader = plane_reader
        self.nblades = nblades
        self.blade_l = blade_length
        self.blade_w = blade_width
        self.blade_t = blade_thickness
    
    # x, y, z are given as relative coordinates, from 0 to 1
    def draw_blade(self, x, y, z, angle, t, blade_idx=-1):
        # Build relation between the blade coordinates and
        # and the mesh cell.

        # 1. Figure out the bounding box of rotated blade at given position
        # - define 4 vectors for the 'close' rectangle: cbl, cbr, ctl, ctr
        #   and 4 vectors for the 'far' rectangle:      fbl, fbr, ftl, ftr
        #   with 'left/right' (l/r) being aligned with width and x coordinate,
        #   'close/far' (c/f) being aligned with length and y axis,
        #   'top/bottom' (t/b) being aligned with thickness and z axis.
        # cbl = (-self.blade_w / 2, 0, -self.blade_t / 2)
        # cbr = ( self.blade_w / 2, 0, -self.blade_t / 2)
        # ctl = (-self.blade_w / 2, 0,  self.blade_t / 2)
        # ctr = ( self.blade_w / 2, 0,  self.blade_t / 2)
        
        # fbl = (-self.blade_w / 2, self.blade_l, -self.blade_t / 2)
        # fbr = ( self.blade_w / 2, self.blade_l, -self.blade_t / 2)
        # ftl = (-self.blade_w / 2, self.blade_l,  self.blade_t / 2)
        # ftr = ( self.blade_w / 2, self.blade_l,  self.blade_t / 2)


        # Or, considering that z coordinate stays constant:
        cl = (-self.blade_w / 2, 0)
        cr = ( self.blade_w / 2, 0)
        fl = (-self.blade_w / 2, self.blade_l)
        fr = ( self.blade_w / 2, self.blade_l)
        # Calculate rotated coordinates:
        cl_r = rotate_vector(cl, angle)
        cr_r = rotate_vector(cr, angle)
        fl_r = rotate_vector(fl, angle)
        fr_r = rotate_vector(fr, angle)

        xmin = min([cl_r[0], cr_r[0], fl_r[0], fr_r[0]])
        xmax = max([cl_r[0], cr_r[0], fl_r[0], fr_r[0]])
        ymin = min([cl_r[1], cr_r[1], fl_r[1], fr_r[1]])
        ymax = max([cl_r[1], cr_r[1], fl_r[1], fr_r[1]])
        zmin = -self.blade_t / 2
        zmax =  self.blade_t / 2

        if DEBUG:
            mult = 700
            offset = 100
            debug_img = np.ones((offset*2, offset*2, 3), dtype=float)
            # Draw the original box
            cv.line(debug_img, 
                    (int(cl[0] * mult + offset), int(cl[1] * mult + offset)), 
                    (int(cr[0] * mult + offset), int(cr[1] * mult + offset)), 
                    (0, 255, 255), 3)
            cv.line(debug_img, 
                    (int(cl[0] * mult + offset), int(cl[1] * mult + offset)), 
                    (int(fl[0] * mult + offset), int(fl[1] * mult + offset)), 
                    (0, 255, 255), 3)
            cv.line(debug_img, 
                    (int(fr[0] * mult + offset), int(fr[1] * mult + offset)), 
                    (int(fl[0] * mult + offset), int(fl[1] * mult + offset)), 
                    (0, 255, 255), 3)
            cv.line(debug_img, 
                    (int(fr[0] * mult + offset), int(fr[1] * mult + offset)), 
                    (int(cr[0] * mult + offset), int(cr[1] * mult + offset)), 
                    (0, 255, 255), 3)
            # Rotated box
            cv.line(debug_img, 
                    (int(cl_r[0] * mult + offset), int(cl_r[1] * mult + offset)), 
                    (int(cr_r[0] * mult + offset), int(cr_r[1] * mult + offset)), 
                    (0, 255, 0), 2)
            cv.line(debug_img, 
                    (int(cl_r[0] * mult + offset), int(cl_r[1] * mult + offset)), 
                    (int(fl_r[0] * mult + offset), int(fl_r[1] * mult + offset)), 
                    (0, 255, 0), 2)
            cv.line(debug_img, 
                    (int(fr_r[0] * mult + offset), int(fr_r[1] * mult + offset)), 
                    (int(fl_r[0] * mult + offset), int(fl_r[1] * mult + offset)), 
                    (0, 255, 0), 2)
            cv.line(debug_img, 
                    (int(fr_r[0] * mult + offset), int(fr_r[1] * mult + offset)), 
                    (int(cr_r[0] * mult + offset), int(cr_r[1] * mult + offset)), 
                    (0, 255, 0), 2)
            # Rotated (rectangular) box
            cv.line(debug_img, 
                    (int(xmin * mult + offset), int(ymin * mult + offset)), 
                    (int(xmax * mult + offset), int(ymin * mult + offset)), 
                    (255, 255, 0), 1)
            cv.line(debug_img, 
                    (int(xmin * mult + offset), int(ymin * mult + offset)), 
                    (int(xmin * mult + offset), int(ymax * mult + offset)), 
                    (255, 255, 0), 1)
            cv.line(debug_img, 
                    (int(xmin * mult + offset), int(ymax * mult + offset)), 
                    (int(xmax * mult + offset), int(ymax * mult + offset)), 
                    (255, 255, 0), 1)
            cv.line(debug_img, 
                    (int(xmax * mult + offset), int(ymin * mult + offset)), 
                    (int(xmax * mult + offset), int(ymax * mult + offset)), 
                    (255, 255, 0), 1)

        #     cv.imshow('', debug_img)
            cv.imwrite('/app/dbg1.png', debug_img)
        #     cv.waitKey()


        center = rotate_vector((0, self.blade_l), angle)
        center_len = math.sqrt(center[0]**2 + center[1]**2)
        center = (center[0] / center_len, center[1] / center_len)

        # 2. For each cell in the box, find its coordinates 
        x = self.mesh.sizex() * x
        y = self.mesh.sizey() * y
        z = self.mesh.sizez() * z
        mesh_xmin = x + xmin
        mesh_ymin = y + ymin
        mesh_zmin = z + zmin
        mesh_xmax = x + xmax
        mesh_ymax = y + ymax
        mesh_zmax = z + zmax
        idx_xmin, idx_ymin, idx_zmin = self.mesh.coord2idx(mesh_xmin, mesh_ymin, mesh_zmin)
        idx_xmax, idx_ymax, idx_zmax = self.mesh.coord2idx(mesh_xmax, mesh_ymax, mesh_zmax)

        if DEBUG:
            mult = 1500
            offset = 250
            debug_img = np.ones((offset*2, offset*2, 3), dtype=np.uint8) * 255

        idxs_l = set()
        idxs_t = set()
        idxs_y = set()

        max_mapped_value = 0
        for idx_z in range(idx_zmin, idx_zmax + 1):
            for idx_x in range(idx_xmin, idx_xmax + 1):
                for idx_y in range(idx_ymin, idx_ymax + 1):
                        mesh_x, mesh_y, mesh_z = self.mesh.idx2coord(idx_x, idx_y, idx_z)
                        profile_x = mesh_x - x
                        profile_y = mesh_y - y
                        profile_z = mesh_z - z

                        projection_len = profile_x * center[0] + profile_y * center[1]
                        projection = (center[0] * projection_len, center[1] * projection_len)
                        ortho_r = (profile_x - projection[0], profile_y - projection[1])
                        ortho = rotate_vector(ortho_r, -angle)

                        mapping_l = projection_len / self.blade_l
                        mapping_t = ortho[0] / self.blade_w + 0.5
                        mapping_y = 1 - (profile_z / self.blade_t + 0.5)
                        if mapping_l < 0 or mapping_t < 0 or mapping_y < 0 or \
                                        mapping_l > 1 or mapping_t > 1 or mapping_y > 1:
                                continue
                        mapping_dt = self.mesh.dx / self.blade_w
                        mapping_dy = self.mesh.dz / self.blade_t
                        
                        is_reader_debug = False
                        mapped_value = self.plane_reader.sample(mapping_l, mapping_t, mapping_y,
                                                                mapping_dt, mapping_dy, is_reader_debug)
                        if mapped_value > max_mapped_value:
                             max_mapped_value = mapped_value
                        # if np.isnan(mapped_value):
                        #      mapped_value = 0
                        assert mapping_l >= 0, "Wrong mapping index."
                        assert mapping_l <= 1, "Wrong mapping index."
                        assert mapping_t >= 0, "Wrong mapping index."
                        assert mapping_t <= 1, "Wrong mapping index."
                        assert mapping_y >= 0, "Wrong mapping index."
                        assert mapping_y <= 1, "Wrong mapping index."
                        mesh_idx_l = int(mapping_l * 10)
                        mesh_idx_t = int(mapping_t * 10)
                        mesh_idx_y = int(mapping_y * 10)
                        idxs_l.add(mesh_idx_l)
                        idxs_t.add(mesh_idx_t)
                        idxs_y.add(mesh_idx_y)
                        mesh_idx = blade_idx + 10*mesh_idx_l + 10*100*mesh_idx_t + 10*100*100*mesh_idx_y
                        self.mesh.mesh[idx_x, idx_y, idx_z, t] = complex(mapped_value, float(mesh_idx))

                        
                        # self.mesh.mesh[idx_x, idx_y, idx_z, t] = mapped_value
                        
                        if DEBUG and idx_z == int((idx_zmin + idx_zmax) / 2)+1:
                            cv.circle(debug_img, 
                                      (int(profile_x * mult + offset), int(profile_y * mult + offset)),
                                       1, (0, int(mapped_value), 0))
        assert max_mapped_value > 0, "No data written!"

        if DEBUG:
        #     cv.imshow('mapping', debug_img)
            cv.imwrite('/app/dbg2.png', debug_img)
            cv.waitKey()


    # x, y, z are given as relative coordinates, from 0 to 1
    def draw(self, x, y, z, rpm, start_angle=0):
        tstart = 0
        nt = self.mesh.nt()
        tstop = nt * self.mesh.dt
        # Time is given in seconds, so rotations per
        # minute is converted to rotations per second
        rps = rpm / 60
        angle = 0
        for t_idx, t in enumerate(tqdm(np.linspace(tstart, tstop, nt), position=1, leave=False)):
            angle = (t * rps) * 360 + start_angle
            for i in range(self.nblades):
                blade_angle = (angle + i * 360 / self.nblades) % 360

                if DEBUG:
                        print(f"({int(blade_angle * 100) / 100}) ", end='\t')

                self.draw_blade(x, y, z, blade_angle, t_idx, blade_idx=i)
        return angle