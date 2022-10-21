class PAM:

    def __init__(self, config):
        self.config = config
        self.x0 = self.y0 = self.x1 = self.y1 = 0
        self.printer = self.config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.bed_mesh = self.printer.lookup_object('bed_mesh')
        self.offset = self.config.getfloat('offset', 0.)
        self.gcode.register_command('PAM', self.cmd_PAM, desc=("PAM"))
        self.gcode.register_command('MESH_CONFIG', self.cmd_MESH_CONFIG, desc=("MESH_CONFIG"))
        self.printer.register_event_handler("klippy:connect", self.handle_connect)
        self.prime_offset = self.config.getfloat('prime_offset', 35.0)
        self.pam_controls_prime_position = self.config.get('pam_controls_prime_position', 'True')

    def handle_connect(self):
        self.toolhead = self.printer.lookup_object('toolhead')
        self.probe_x_step = float((self.bed_mesh.bmc.orig_config['mesh_max'][0] - self.bed_mesh.bmc.orig_config['mesh_min'][0]) / self.bed_mesh.bmc.orig_config['x_count'])
        self.probe_y_step = float((self.bed_mesh.bmc.orig_config['mesh_max'][1] - self.bed_mesh.bmc.orig_config['mesh_min'][1]) / self.bed_mesh.bmc.orig_config['y_count'])

    def cmd_MESH_CONFIG(self, param):
        self.x0 = param.get_float('X0', None, -1000, maxval=1000)
        self.y0 = param.get_float('Y0', None, -1000, maxval=1000)
        self.x1 = param.get_float('X1', None, -1000, maxval=1000)
        self.y1 = param.get_float('Y1', None, -1000, maxval=1000)
        if self.x0 < 0 or self.y0 < 0:
            self.gcode.respond_raw("Wrong first layer coordinates!")
        else:
            if self.pam_controls_prime_position == 'True':
                self.gcode.respond_raw("PAM: Trying to establish prime line/blob position relative to PAM")
                ppd = self.find_prime_position()
                if ppd['x_placed'] and ppd['y_placed']:
                    self.gcode.respond_raw("PAM: Prime position: x={x}, y={y}. Orientation: {ox}, {oy}, {d}".format(
                        x=ppd['prime_pos_x'], y=ppd['prime_pos_y'], ox=ppd['orientation_x'], oy=ppd['orientation_y'], d=ppd['prime_direction']))
                    self.gcode.run_script_from_command("SET_GCODE_VARIABLE MACRO=RatOS VARIABLE=nozzle_prime_start_x "
                                                       "VALUE={x}".format(x=ppd['prime_pos_x']))
                    self.gcode.run_script_from_command("SET_GCODE_VARIABLE MACRO=RatOS VARIABLE=nozzle_prime_start_y "
                                                       "VALUE={y}".format(y=ppd['prime_pos_y']))
                    self.gcode.run_script_from_command("SET_GCODE_VARIABLE MACRO=RatOS VARIABLE=nozzle_prime_direction "
                                                       "VALUE=\"\'{d}\'\"".format(d=ppd['prime_direction']))
                else:
                    self.gcode.respond_raw("PAM: Can't find a good position for the prime line/blob, using default "
                                           "position")
                    self.gcode.run_script_from_command("SET_GCODE_VARIABLE MACRO=RatOS VARIABLE=nozzle_prime_start_x "
                                                       "VALUE=\"\'max\'\"")
                    self.gcode.run_script_from_command("SET_GCODE_VARIABLE MACRO=RatOS VARIABLE=nozzle_prime_start_y "
                                                       "VALUE=\"\'min\'\"")
                    self.gcode.run_script_from_command("SET_GCODE_VARIABLE MACRO=RatOS VARIABLE=nozzle_prime_direction "
                                                       "VALUE=\"\'auto\'\"")

    def find_prime_position(self):
        # Tries to select the best position for the prime blob / line and check if it falls inside the bed
        ppd = {'x_placed': False, 'y_placed': False}
        min_x = self.bed_mesh.bmc.orig_config['mesh_min'][0]
        min_y = self.bed_mesh.bmc.orig_config['mesh_min'][1]
        max_x = self.bed_mesh.bmc.orig_config['mesh_max'][0]
        max_y = self.bed_mesh.bmc.orig_config['mesh_max'][1]
        # select best position for prime line/blob
        if self.x0 - min_x > max_x - self.x1:
            ppd['prime_pos_x'] = self.x0 - self.prime_offset   # left
            ppd['orientation_x'] = 'left'
        else:
            ppd['prime_pos_x'] = self.x1 + self.prime_offset   # right
            ppd['orientation_x'] = 'right'
        if self.y0 - min_y > max_y - self.y1:
            ppd['prime_pos_y'] = self.y0 - self.prime_offset   # front
            ppd['prime_direction'] = 'forwards'
            ppd['orientation_y'] = 'front'
        else:
            ppd['prime_pos_y'] = self.y1 + self.prime_offset   # back
            ppd['prime_direction'] = 'backwards'
            ppd['orientation_y'] = 'back'
        # check that prime line/blob is inside the bed_mesh
        if min_x < ppd['prime_pos_x'] < max_x:
            ppd['x_placed'] = True
        if ppd['prime_direction'] == 'forwards' and ppd['prime_pos_y'] > min_y and ppd['prime_pos_y'] + 100 < max_y:
            ppd['y_placed'] = True
        if ppd['prime_direction'] == 'backwards' and ppd['prime_pos_y'] < max_y and ppd['prime_pos_y'] - 100 > min_y:
            ppd['y_placed'] = True
        return ppd

    def cmd_PAM(self, param):
        if self.x0 >= self.x1 or self.y0 >= self.y1:
            self.gcode.run_script_from_command('BED_MESH_CALIBRATE PROFILE=ratos')
            return
        mesh_x0 = max(self.x0 - self.offset, self.bed_mesh.bmc.orig_config['mesh_min'][0])
        mesh_y0 = max(self.y0 - self.offset, self.bed_mesh.bmc.orig_config['mesh_min'][1])
        mesh_x1 = min(self.x1 + self.offset, self.bed_mesh.bmc.orig_config['mesh_max'][0])
        mesh_y1 = min(self.y1 + self.offset, self.bed_mesh.bmc.orig_config['mesh_max'][1])
        mesh_cx = max(3, int((mesh_x1 - mesh_x0) / self.probe_x_step))
        mesh_cy = max(3, int((mesh_y1 - mesh_y0) / self.probe_y_step))
        if self.bed_mesh.bmc.orig_config['algo'] == 'lagrange' or (self.bed_mesh.bmc.orig_config['algo'] == 'bicubic' and (mesh_cx < 4 or mesh_cy < 4)):
            mesh_cx = min(6, mesh_cx)
            mesh_cy = min(6, mesh_cy)
        self.gcode.respond_raw("PAM v0.1.0 bed mesh leveling...")
        self.gcode.run_script_from_command('BED_MESH_CALIBRATE PROFILE=ratos mesh_min={0},{1} mesh_max={2},{3} probe_count={4},{5} relative_reference_index=-1'.format(mesh_x0, mesh_y0, mesh_x1, mesh_y1, mesh_cx, mesh_cy))


def load_config(config):
    return PAM(config)
