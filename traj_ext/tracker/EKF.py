########################################################################################
#
# Implementation of an Extended Kalman Filter for Vehicle Tracking from Image Detection
# Parent Class
#
########################################################################################


import numpy as np;
import matplotlib.pyplot as plt
from  math import *;
import os
import cv2
import copy
import sys
import abc

from tracker import cameramodel as cm
from utils.mathutil import *

class TrajPoint():
    def __init__(self, time_ms, x, y, vx, vy, psi_rad):
        self.time_ms = time_ms;
        self.x = x;
        self.y = y;
        self.vx = vx;
        self.vy = vy;
        self.psi_rad = psi_rad;

class MeasStruct():
    def __init__(self, time_ms, pix_meas_2D):
        self.time_ms = time_ms;
        self.pix_meas_2D = pix_meas_2D;

        # Making sure pix_meas is the right format / size
        if not (pix_meas_2D.shape == (2,1)):
            raise NameError('MeasStruct size is not correct')

class MeasBox3D():
    def __init__(self, time_ms, box3D):
        self.time_ms = time_ms;
        self.box3D = box3D;

class StateStruct():
    def __init__(self, time_ms, x_state, P_cov):
        self.time_ms = time_ms;
        self.x_state = x_state;
        self.P_cov = P_cov;

class EKF_track(abc.ABC):

    def __init__(self, Q_mat, R_mat, x_init, P_init, track_id, t_current_ms, label):

        # Tracker ID:
        self.track_id = track_id

        # Store Process and Measurement noise covariance matrix
        self.Q_mat = Q_mat;
        self.R_mat = R_mat;

        # Init variables
        self.x_current = x_init;
        self.P_current = P_init;

        # Init last measurement: Pixel location
        self.meas_dim = 2;

        # Save init time
        self._init_time_ms = t_current_ms;

        # Generate a random color - Unique for this track
        self.color = (int(np.random.randint(0,255,1)[0]), int(np.random.randint(0,255,1)[0]), int(np.random.randint(0,255,1)[0]));
        self.label = label

        # Store past box3D measurement
        self._box3D_meas_list = [];
        self._box3D_meas_list_len = 90;

        # Store past box3D measurement
        self._meas_list = [];
        self._meas_list_len = 90;

        # Keep track of meas and state:
        self.x_list = [];
        self.x_list_len = 90;

        # Init filer param from child implementation
        self.state_dim = self.get_state_dim();
        self._last_time_predict_ms = t_current_ms

        # Store past predictions
        self.history_fuse_states = []
        self.history_predict_states = []

        self.history_processed_states = []
        self.last_time_ms = None

        # Init smoother variables
        self.history_smooth_states = []

        self.x_smooth = x_init;
        self.P_smooth = P_init;
        self.traj_smoothed = [];

        self._tk_active = True

        self.merged_ids = [];

    """
    Abstract method: Must be implemented in the child implementation
    Return:
        - state_dim  Dimension of the state
    """
    @abc.abstractmethod
    def get_state_dim(self):
        pass;


    @abc.abstractmethod
    def create_x_init(self, Box3D):
        """ Abstract method: Must be implemented in the child implementation
            Create a State from a Box3D used for init the filer in the constructor

        Args:
            Box3D (TYPE): Numpy array [phi, x, y, z, l, w, h]

        Returns:
            numpy array: State used for filter initialization

        """
        pass;

    @abc.abstractmethod
    def get_A_model(self, x_current):
        return A;

    @abc.abstractmethod
    def propagate_state(self, x_current, delta_s):
        """ Abstract method: Must be implemented in the child implementation
            Propagate the state according to the model's dynamic

        Args:
            x_current (TYPE): Description

            delta_s (TYPE): Description

        Returns:
            TYPE: state propagated accoring according to the model's dynamic

        """
        return x_prop;

    @abc.abstractmethod
    def compute_meas_H(self, cam_model, x_current = None):
        return H;

    @abc.abstractmethod
    def get_processed_parameters_filter(self, current_time_ms):
        return xy, vxy, phi_rad;

    @abc.abstractmethod
    def get_processed_parameters_smoothed(self, current_time_ms):
        return xy, vxy, phi_rad;

    def get_color(self):
        return self.color;

    @abc.abstractmethod
    def trajpoint_from_state(self, state):
        return trajpoint;

    def get_state_smooth_at_time(self, t_current_ms):

        smooth_state = None;

        smooth_data = self.get_tk_smooth(t_current_ms);
        if not (smooth_data is None):
            smooth_state = smooth_data.x_state;

        return smooth_state;

    def get_traj_smooth(self, t_current_ms, past_step):

        index = None;
        for i, smooth_s in enumerate(reversed(self.history_smooth_states)):
            if smooth_s.time_ms == t_current_ms:
                index = i;

        list_trajpoint = [];
        if not(index is None):
            i_start = index;
            i_end = min((index + past_step), len(self.history_smooth_states));
            for i, smooth_s in enumerate(reversed(self.history_smooth_states)):
                if i > i_start and i < i_end:

                    traj_point = self.trajpoint_from_state(smooth_s);
                    list_trajpoint.append(traj_point)

        return list_trajpoint;

    def set_x_init(self, Box3D):
        """Summary

        Args:
            Box3D (TYPE)
        """

        self._box3D_init = Box3D;
        self.x_current = self.create_x_init(Box3D);
        self.x_list.append(self.x_current);

        self.save_predict_history(self._init_time_ms);


    def push_3Dbox_meas(self, time_ms, box3D_meas):
        """Push 3D box measurement

        Args:
            time_ms (TYPE): Description
            box3D_meas (TYPE): Description

        Returns:
            TYPE: Description
        """
        if box3D_meas is None:
            print('[Error] : EKF push_3Dbox_meas box3D_meas is None')

        box3D_meas_data = MeasBox3D(time_ms, box3D_meas);
        self._box3D_meas_list.append(box3D_meas_data);
        # if(len(self._box3D_meas_list) > self._box3D_meas_list_len):
        #     self._box3D_meas_list.pop(0);

        return;

    def _push_pix_meas(self, time_ms, pix_meas):
        """Push 3D box measurement

        Args:
            time_ms (TYPE): Description
            box3D_meas (TYPE): Description

        Returns:
            TYPE: Description
        """
        if pix_meas is None:
            print('[Error] : EKF kf_fuse pix_meas is None')

        meas_data = MeasStruct(time_ms, pix_meas);
        self._meas_list.append(meas_data);
        # if(len(self._meas_list) > self._meas_list_len):
        #     self._meas_list.pop(0);

        return;

    def get_last_meas_time_ms(self):

        last_meas_time_ms = None;
        if len(self._meas_list) > 0:
            last_meas_time_ms = self._meas_list[-1].time_ms;

        return last_meas_time_ms;

    def save_states(self, current_time_ms):
        """Call functions to save history of predictions of Kalman filter

        Args:
            current_time (float)
        """
        self.save_fuse_history(current_time_ms)
        self.save_predict_history(current_time_ms)
        # self.save_processed_history(current_time)

    def save_fuse_history(self, current_time_ms):
        """Save history of predictions updated by mesurements

        Args:
            current_time (sloat)
        """

        # Create list data
        state_data = StateStruct(current_time_ms, self.x_current, self.P_current);

        # Add state data to history list
        self.history_fuse_states.append(state_data)
        # if len(self.history_fuse_states) > 100:
        #     self.history_fuse_states.pop(0)

    def save_predict_history(self, current_time_ms):
        """ Save gistory of predictions

        Args:
            current_time (float):
        """

        # Create list data
        state_data = StateStruct(current_time_ms, self.x_current, self.P_current);

        # Add state data to history list
        self.history_predict_states.append(state_data)
        # if len(self.history_predict_states) > 100:
        #     self.history_predict_states.pop(0)

    # def save_processed_history(self, current_time):
    #     """Save history of predictions updated by mesurements

    #     Args:
    #         current_time (sloat)
    #     """
    #     # Delete obsolete predictions

    #     try:
    #         index = next(idx for idx, dict_class in enumerate(self.history_processed_states) if dict_class["timestamp"] == current_time)
    #         self.history_processed_states.pop(index)
    #     except:
    #         pass;

    #     xy, vxy, phi_rad, box3D_meas = self.get_processed_parameters_filter(current_time)
    #     dict_state = {  'timestamp' : current_time,
    #                     'xy'        : xy,
    #                     'vxy'       : vxy,
    #                     'phi_rad'   : phi_rad,
    #                     '3Dbox_meas': box3D_meas}

    #     self.history_processed_states.append(dict_state)

    #     if len(self.history_processed_states) > 100:
    #         self.history_processed_states.pop(0)

    def get_3Dbox_meas(self, current_time_ms):
        """ Return the filtered position

        Returns:
            numpy array 21: position x, position y
        """
        box3D_meas = None
        count = 0

        for box3D_data in self._box3D_meas_list:

            if box3D_data.time_ms == current_time_ms:
                box3D_meas = box3D_data.box3D;
                break;

        return box3D_meas;

    def get_filt_pos(self, current_time_ms):
        """ Return the filtered position

        Returns:
            numpy array 21: position x, position y
        """
        # pos_21 = None
        # count = 0

        # while (pos_21 is None) and (count < len(self.history_processed_states)):

        #     obj = self.history_processed_states[count]

        #     if obj['timestamp'] == current_time:
        #         pos_21 = np.array([obj['xy'][0], obj['xy'][1]])

        #     count += 1

        # return pos_21;

        xy, vxy, phi_rad = self.get_processed_parameters_filter(current_time_ms);

        return xy;

    def get_filt_vel(self, current_time_ms):
        """ Return the filtered velocity

        Returns:
            numpy array 21: velocity x, velocity y
        """
        # vel_21 = None
        # count = 0

        # while (vel_21 is None) and (count < len(self.history_processed_states)):

        #     obj = self.history_processed_states[count]

        #     if obj['timestamp'] == current_time:
        #         vel_21 =  np.array([obj['vxy'][0], obj['vxy'][1]]);

        #     count +=  1
        # return vel_21;

        xy, vxy, phi_rad = self.get_processed_parameters_filter(current_time_ms);

        return vxy;

    def get_filt_phi(self, current_time_ms):
        """ Return the filtered phi (orientation angle)

        Returns:
            float: Phi angle in radians
        """

        xy, vxy, phi_rad = self.get_processed_parameters_filter(current_time_ms);

        return phi_rad;


   # Create a 3D box accorign to the filtered state
    def get_3Dbox_filt(self, current_time_ms):

        box3D_filt = copy.copy(self._box3D_init);

        pos_21 = self.get_filt_pos(current_time_ms);
        phi_rad = self.get_filt_phi(current_time_ms);

        if not(pos_21 is None) and not(phi_rad is None):
            box3D_filt[0] = np.rad2deg(phi_rad)
            box3D_filt[1] = pos_21[0]
            box3D_filt[2] = pos_21[1]

        else:
            box3D_filt = None

        return box3D_filt

    def _update_is_active(self, current_time_ms):
        """Check if the track is still active based on enough measurement in the last X seconds
            Shoudl be changed on a check on the P covriance matrix measure

        Args:
            current_time (float): Current time in seconds

        Returns:
            BOOL: active of not_active flag
        """

        # Do not deactivate for the first few seconds
        if current_time_ms - self._init_time_ms > 1000:

            count = 0;
            for meas_data in self._meas_list:
                if abs(meas_data.time_ms - current_time_ms) < 1000: #0.5: # Tune this value as a function of timestep
                    count +=1;

            self._tk_active = (count >= min(2, len(self._meas_list)));

    def is_active(self):
        return self._tk_active;

    def kf_predict(self, current_time_ms):
        """ Compute prediction using Kalman equations:
                x_(t+1) = f_t(x_t) = F_t . x_t
                P_(t+1)  = F_t . P_t . (F_t).T + Q_t
                Note that : ().T is for transpose and ()^(-1) is for inverse
        Args:
            current_time (float)
        """

        self._update_is_active(current_time_ms);

        # Propagate the state
        delta_s = float(current_time_ms - self._last_time_predict_ms)/float(1e3);

        self.x_current = self.propagate_state(self.x_current, delta_s);

        # First order approx
        F = np.identity(self.state_dim) + self.get_A_model(self.x_current)*delta_s;
        Q_dis = self.Q_mat*delta_s;

        # Covariance update
        self.P_current = F.dot(self.P_current.dot(F.transpose())) + Q_dis;
        self.P_current = (self.P_current + self.P_current.transpose())/2;

        # Log state:
        self.x_list.insert(0, self.x_current);

        # if len(self.x_list) > self.x_list_len:
        #     self.x_list.pop(0);

        # self.save_state_predict(current_time)
        self._last_time_predict_ms = current_time_ms

        self.save_predict_history(current_time_ms)

            # self.save_processed_history(current_time)

    def compute_pix_pred(self, cam_model):
        """ Project real world coordinate points to image pixels

        Args:
            cam_model (CameraModel object)

        Returns:
            list
        """
        # Update state:
        pos_F = np.asarray(self.x_current[0:2,0]).reshape(-1);
        pos_F = np.append(pos_F, 0);

        # Project the current estimate on the image place according to the cam_model
        pix_pred = cam_model.project_points(pos_F);
        pix_pred.shape = (2,1);

        return pix_pred;


    def kf_fuse(self, pix_meas, cam_model, current_time_ms):
        """Compute prediction merging measurements:
                K_(t+1) = P_t . (H_t).T . (R_t + H_t . P_t . (C_t).T)^(-1)
                x_(t+1) = x_t + K_t . (y_t - ŷ_t)
                P_(t+1) = P_t - K_t . H_t . (P_t).T

        Args:
            pix_meas (list): Description
            cam_model (CameraModel object)
            current_time_ms (float)
        """

        # Add pix meas to the history
        self._push_pix_meas(current_time_ms, pix_meas);

        # Compute Kalman gain:
        H = self.compute_meas_H(cam_model, self.x_current);
        S = self.compute_S(cam_model);
        K = self.P_current.dot(H.transpose().dot(np.linalg.inv(S)))

        # Compute measurement estimate (from the current state)
        pix_pred = self.compute_pix_pred(cam_model);

        # Udpate the current estimate
        pix_pred.shape = (2,1);
        pix_meas.shape = (2,1);
        self.x_current = self.x_current + K.dot(pix_meas - pix_pred)

        # Update Covariance:
        self.P_current = (np.identity(self.state_dim) - K.dot(H)).dot(self.P_current);
        self.P_current = (self.P_current + self.P_current.transpose())/2;

        self.save_fuse_history(current_time_ms);

    def compute_S(self, cam_model):
        """Summary

        Args:
            cam_model (TYPE)

        Returns:
            TYPE: Description
        """
        H = self.compute_meas_H(cam_model, self.x_current);

        S = self.R_mat + H.dot(self.P_current.dot(H.transpose()));

        return S;


    def reset_smoother(self):
        """ Reset variable at time step zero for each smoothing step
        """
        self.x_smooth = None

    def is_clean(self, current_time_ms):

        clean = abs(current_time_ms - self.last_time_ms) <= 100;

        return clean

    def smooth(self, list_times_ms, post_proces = False):

        # Smooth from the last fused time to the time smooth
        self.reset_smoother()
        for idx, current_time_ms in reversed(list(enumerate(list_times_ms))):

            if self.x_smooth is None:

                self.init_smoother(current_time_ms)

            else:

                self.back_propagation(current_time_ms, list_times_ms[0])

            # If in post process mode: Save smoothed during the backpropagation
            if post_proces:
                self.save_smooth_history(current_time_ms, reverse = True)
                self.push_trajectory()

        # If not in post-process: save the samoothed satate only at the end since running window
        if not post_proces:
            self.save_smooth_history(list_times_ms[0])
            self.push_trajectory()


    def init_smoother(self, current_time_ms):
        """ Initalize state of smoother for last timestep of window

        Args:
            current_time (float)
        """
        tk_fuse  = self.get_tk_fuse(current_time_ms)

        if not (tk_fuse is None):
            self.x_smooth = tk_fuse.x_state;
            self.P_smooth = tk_fuse.P_cov;
            self.last_time_ms = current_time_ms
        else:
            print('[Error]: No tk_fuse to reset smoother')


    def push_trajectory(self):
        """ Store smoothed predition history
        """
        if not(self.x_smooth is None):
            self.traj_smoothed.insert(0, self.x_smooth)

        # if len(self.traj_smoothed) > 90:
        #     self.traj_smoothed.pop();

    def get_tk_fuse(self, current_time_ms):

        tk_fuse = None

        for index, tk in enumerate(self.history_fuse_states):
            if tk.time_ms == current_time_ms:
                tk_fuse = self.history_fuse_states[index]
                break;

        return tk_fuse

    def get_tk_predict(self, current_time_ms):

        tk_predict = None

        for index, tk in enumerate(self.history_predict_states):
            if tk.time_ms == current_time_ms:
                tk_predict = self.history_predict_states[index]
                break;

        return tk_predict

    def back_propagation(self, current_time_ms, first_time_step):
        """ Compute the predictions of smoother throughout the window using Kalman smoother equations:
                L_t = P_t . (F_t).T . (P_t+1)^(-1)
                x_t = x_t + L_t . (x_(t+1)(previous) - F_t.x_t)
                P_t = P_t + L_t . (P_(t+1)(previous) - P_(t+1)) . (L_t).T

        Args:
            current_time (float)
        """

        # Careful: make  it slow
        delta_s = fabs(float(current_time_ms - self.last_time_ms)/float(1e3));
        tk_fuse = self.get_tk_fuse(current_time_ms)

        # At last time step, if no measurement get predicted value
        # if (tk_fuse is None) and current_time == first_time_step:
        if (tk_fuse is None):

            tk_fuse = self.get_tk_predict(current_time_ms)

        if not(tk_fuse is None):

            tk_predict = self.get_tk_predict(self.last_time_ms)

            # Define matrix L
            F = np.identity(self.state_dim) + self.get_A_model(tk_fuse.x_state)*delta_s;

            L = tk_fuse.P_cov.dot(F.transpose().dot(np.linalg.inv(tk_predict.P_cov)))

            self.x_smooth = tk_fuse.x_state+ L.dot(self.x_smooth - tk_predict.x_state)

            self.P_smooth = tk_fuse.P_cov + L.dot((self.P_smooth - tk_predict.P_cov).dot(L.transpose()))

            # Save previous trajectories for plotting:
            self.last_time_ms = current_time_ms;

    def save_smooth_history(self, current_time_ms, reverse = False):

        # Save smooth states and parameters if computed

        if current_time_ms == self.last_time_ms and not(self.x_smooth is None):

            # xy, vxy, phi_rad = self.get_processed_parameters_smoothed(current_time)
            # dict_state = {'timestamp' : current_time_ms,
            #                 'x_smooth': self.x_smooth,
            #                 'P_smooth': self.P_smooth,
            #                 'xy'      : xy,
            #                 'vxy'     : vxy,
            #                 'phi_rad' : phi_rad}

            state_data = StateStruct(current_time_ms, self.x_smooth, self.P_smooth);

            if reverse:
                self.history_smooth_states.insert(0,state_data)
            else:
                self.history_smooth_states.append(state_data)


            # if len(self.history_smooth_states) > 100:
            #     self.history_smooth_states.pop(0)

    def get_3Dbox_smooth(self, current_time_ms):

        box3D_sm = copy.copy(self._box3D_init)

        pos_21 = self.get_smooth_pos(current_time_ms);
        phi_rad = self.get_smooth_phi(current_time_ms);

        if not(pos_21 is None) and not(phi_rad is None):
            box3D_sm[0] = np.rad2deg(phi_rad)
            box3D_sm[1] = pos_21[0]
            box3D_sm[2] = pos_21[1]

        else:
            box3D_sm = None

        return box3D_sm;

    def get_tk_smooth(self, current_time_ms):

        tk_smooth = None

        for index, tk in enumerate(self.history_smooth_states):
            if tk.time_ms == current_time_ms:
                tk_smooth = self.history_smooth_states[index]
                break;

        return tk_smooth;

    def get_smooth_pos(self, current_time_ms):
        """ Return the filtered position

        Returns:
            numpy array 21: position x, position y
        """
        # pos_21 = None

        # tk_smooth = self.get_tk_smooth(current_time)

        # if not(tk_smooth is None):

        #     pos_21 = tk_smooth['xy']


        # return pos_21;

        xy, vxy, phi_rad = self.get_processed_parameters_smoothed(current_time_ms);

        return xy;

    def get_smooth_vel(self, current_time_ms):
        """ Return the filtered velocity

        Returns:
            numpy array 21: velocity x, velocity y
        """
        # vel_21 = None

        # tk_smooth = self.get_tk_smooth(current_time)

        # if not(tk_smooth is None):

        #     vel_21 = tk_smooth['vxy']

        # return vel_21;

        xy, vxy, phi_rad = self.get_processed_parameters_smoothed(current_time_ms);

        return vxy;


    def get_smooth_phi(self, current_time_ms):
        """ Return the filtered phi (orientation angle)

        Returns:
            float: Phi angle in radians
        """
        # phi_rad = None

        # tk_smooth = self.get_tk_smooth(current_time)

        # if not(tk_smooth is None):

        #     phi_rad = tk_smooth['phi_rad']

        # return phi_rad;

        xy, vxy, phi_rad = self.get_processed_parameters_smoothed(current_time_ms);

        return phi_rad;