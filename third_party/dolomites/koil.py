import sys
from dataclasses import dataclass

import numpy as np
import math, cmath

import matplotlib.pyplot as plt


class coil ():
    """
    A class to represent a single coil in the winding.

    Attributes
    ----------
    begin : int
            the begin slot (in the range 1..Q)
    end   : int
            the end slot (in the range 1..Q)
    nc    : int
            the number of conductors
    """
    def __init__(self, begin, end, nc):
        self.begin = begin;
        self.end   = end;
        self.nc    = nc;
    def __repr__(self):
        return "coil (%s, %s, %s)" % (self.begin, self.end, self.nc)



class winding():
    """
    A class to collect a set of Coil.
    It can be considered as the set of coils that forms one phase
    """

    def __init__(self,Q,p):
        self.Q = Q
        self.p = p
        self.coils = []
        self.slot_matrix = np.zeros(Q)

    def add_coil(self,c):
        self.coils.append(c)

    def get_kw(self, nu = None, angles = None ):
         """
         # compute the winding factor for a specific harmonic nu
         # custom angles can be specified. Default values are regularly spaced
         # slots around the airgap. Mechanical radians are expected in alngles
         """

         if nu is None:
             nu = self.p
         if angles is None:
             angles = np.linspace(0,2 * math.pi*nu, self.Q+1)
             #print(' Computing winding factor.\n Using regularly distributed angles')
         else:
             angles = np.asarray(angles)*nu # convert in electrical radians the angles
             #print(' Computing winding factor.\n Using custom angles')
         if not self.compute_slot_matrix():
             return -1;

         val = 0;
         X=0; Y=0; R=0; N=0; angle = 0;
         for i in range(self.Q):
           val = self.slot_matrix[i];
           angle = angles[i]
           if (val<0):
               val = -val;
               angle = angle + math.pi
           X = X + val * math.cos(angle);
           Y = Y + val * math.sin(angle);
           N = N + val;
         R = math.sqrt(X*X+Y*Y);
         if(R/N<1e-8):
             return 0;
         return R/N;

    def compute_slot_matrix(self):
        """
        Compute the slot matrix on the basis of the coils added to the winding
        """

        if (len(self.coils)<1):
            return False;
        self.slot_matrix = np.zeros(self.Q)
        for coil in self.coils:
            self.slot_matrix[coil.begin - 1] += coil.nc
            self.slot_matrix[coil.end - 1]   -= coil.nc
        return True;

    def get_slot_matrix(self, format=None, normalize=True, name=''):
        """ Return teh slot matrix of the winding.

        Parameters:
        -----------
            format: specify the format. Available formats are:
            None: for internal use only (default)
            txt:
            lua:
            getdp:
            getdp-2l:
            m-file:

            normalize: allows to expres in the per unit the number of conductors within each slots
            name: allows to specify a name of the phase the winding is associated with
        """
        self.compute_slot_matrix();


        max = 0
        if (normalize):
            for  i in self.slot_matrix:
                if (abs(i) > max):
                    max = i;
        else:
            max = 1;

        if format == None:
            return self.slot_matrix/max;
        elif (format =="txt"):    # No particular format at all
            return name+': ['+','.join(str(x/max) for x in self.slot_matrix)+']';

        elif (format =="lua"): # lua scripting format, i.e. for Femm
            return 'k'+name+' = {'+','.join(str(x/max) for x in self.slot_matrix)+'}';

        elif (format =="getdp"):# GetDP format
            s = ''
            for  i in range(len(self.slot_matrix)):
                s = s+'k' + name + '[#' + str(1001+i) + '] = ' + str(self.slot_matrix[i]/max) +';\n'
            return s

        elif (format =="getdp-2l"):# GetDP format with two layer information (useful when circuit are used)
            s = ''
            l1 = np.zeros(self.Q)
            l2 = np.zeros(self.Q)
            for  c in self.coils:
                l1[c.begin-1] += c.nc
                l2[c.end-1]   -= c.nc
            for  i in range(len(self.slot_matrix)):
                s = (s+'k' + name + '[#' + str(1001+i) + '] = ' + str(l1[i]/max) + ';'  +
                      ' k' + name + '[#' + str(2001+i) + '] = ' + str(l2[i]/max) + ';\n')
            return s
        elif (format =="m-file"): # matlab format
            return 'k' + name + ' = ['+','.join(str(x/max) for x in self.slot_matrix)+'];';

    def get_getdp_circuit(self, name = 'a', id=100):
        """
        Return a circuit representation of the coils in the winding.
        Useful to be adopted in GetDP projects.
        Parameters:
        -----------
        name: the name used for the circuit,i.e. the phase name (default a)
        id:   the starting id number used for the node in the circuit (default 100)
        """
        # TODO fix the region numbers for single layer windings

        circuit = ''

         # print the string:  Case Circuit_name {
        circuit += 'Case Circuit_';
        circuit += name;
        circuit += ' {\n';

        index = id;
        for coil in self.coils:
            if (coil.nc>0):
                circuit += '    {Region #' + str(coil.begin+1000) + '; Branch {'+ str(index)   + ',' + str(index+1) + '};}\n'
                circuit += '    {Region #' + str(coil.end+2000) + '; Branch {'+ str(index+2) + ',' + str(index+1) + '};}\n'
            else:
                circuit += '    {Region #' + str(coil.end+2000) + '; Branch {'+ str(index)   + ',' + str(index+1) + '};}\n'
                circuit += '    {Region #' + str(coil.begin+1000) + '; Branch {'+ str(index+2) + ',' + str(index+1) + '};}\n'
            index+=2;
        circuit += '    {Region #G' + name + '; Branch {' + str(id) + ',' + str(index)+'};}\n'
        circuit += '    }\n';

        return circuit;





@dataclass
class spoke():
    id: int      # The index of the spoke (the related slot number)
    angle: float # The angle of the spoke in radians
    def __repr__(self):
        return "Spoke %s: angle %s" % (self.id, self.angle*180/math.pi)


class sector():
    def __repr__(self):
        return "Sector, start: %s, end: %s, slots: %s" % (self.start_angle*180/math.pi, self.end_angle*180/math.pi, self.slots)
    def __init__(self,start,end):
        self.start_angle = start   # The start angle of the phasor
        self.end_angle   = end     # The end angle of the phasor
        self.slots = [];           # The list of slots that belong to the sector

    def angle_inside(self,angle):
        """
        Return true if the given angle is inside the sector
        """
        #The first sector is always centered on the origin axis and has to be trated carefully
        # This should be removed after the introduction of offset in the sectors
        #if(self.start_angle<0):
                #add = self.end_angle;
                #angle += add;
                #while (angle > 2*math.pi):
                    #angle -= 2*math.pi;
                #if (angle > 0 and angle < self.end_angle+add):
                    #return True;

        if (angle > self.start_angle and angle < self.end_angle):
            return True;
        return False;

    def normalize_angles(self):
        """
        Makes the angles of the sector in the range 0 - 2*pi
        """
        while (self.start_angle >= 2*math.pi):
            self.start_angle -= 2*math.pi;
        while (self.end_angle   > 2*math.pi):
            self.end_angle   -= 2*math.pi;



class star_of_slot():
    def __repr__(self):
        res = """
              Sos: (m: %s, Q: %s, p: %s, t: %s, yq: %s)
              Spokes: %s
              Positive sectors: %s
              Negative sectors: %s
              """ % (self.m, self.Q, self.p, self.t, int(self.Q/2/self.p),self.star,self.p_sec,self.n_sec)
        return res

    def __init__ (self,m, Q, p):
        self.m = m
        self.Q = Q
        self.p = p
        self.t = self.gcd(Q,p); # Compute the machine periodicity
        self.yq = int(Q/2/p)    # Compute the theoretical coil throw
        if (self.yq<1):
            self.yq = 1
        self.mutual_inductance_zero = False
        self.single_layer_feasible  = False
        self.single_layer    = False
        self.star = []  # A list containing the star's spokes number sequence
        self.p_sec= []  # A list containing the positive sectors of the star. The sectors are m
        self.n_sec= []  # A list containing the negative sectors of the star. The sectors are m


        # Winding feasibility check
        if ( int(Q/(m*self.t)) != float(Q/(m*self.t))):
            self.t = -1;
        # Check for balanced winding with even number of phases
        elif ((self.gcd(m,2)==2) and (self.gcd(Q/(m*self.t),2)!=2)):
            self.t = -1;

        else:  #  Q/ (m*t) is integer and  the winding is feasible

                # Single layer feasibility and mutual inductance check
                if(self.gcd(Q,2)!=2):
                    self.single_layer_feasible = False; # Q is odd. SL winding is feasible only if Q is even

                else: # Q is even
                      if ( self.gcd (Q/self.t , 2 ) != 2 ): #  Q/t odd
                          self.mutual_inductance_zero = False;
                          if   ( (self.t%2) != 0 ):
                              self.single_layer_feasible = False; # Q/t is odd and t is odd
                          else:
                              self.single_layer_feasible = True;  # Q/t is odd and t is even
                      else:  #  Q/t even
                        if ( self.gcd(Q/(2*self.t) , 2) ==2 ):           #  Q / ( 2t ) even
                            self.single_layer_feasible = True;      #  Q/t is even and Q/(2t) is even;
                            if (self.yq==1):
                                self.mutual_inductance_zero = True; #  M is 0 for both SL and DL winding if yq = 1

                        else:  #  Q / ( 2t ) odd
                            self.single_layer_feasible = True;       # Q/t is even and Q/(2t) is odd
                            if (self.yq==1):
                                self.mutual_inductance_zero = True;  # M is 0 if yq = 1
                            if (self.single_layer):
                                self.mutual_inductance_zero = False; # M is 0 only for double layer winding
        # The winding is feasible and the star is created
        self.create_star()

    def create_star(self): # Create the star of slot populating the spokes

        # clear all the quantities that will be computed
        self.star.clear();

        alpha_se = 2 * math.pi / self.Q * self.p # Slot electrical angle
        alpha_ph = 2 * math.pi / self.Q * self.t # Angle between two adiacent phasor (or star spoke)

        # we define the angle epsilon as an offset for the spokes
        # in case they lay on the sector border, i.e. some problem
        # could rises in the the angle_inside() function
        epsilon = 0;

        # we try to define a proper value for epsilon depending on the number of spokes and phases
        spoke_per_phase = self.Q/(self.m*self.t)

        if (self.m % 2) != 0: # m  is odd
            if ( spoke_per_phase == 1 or  spoke_per_phase == 2):# we have 1 spoke for each phase
                epsilon = math.pi/self.m/2
            elif (spoke_per_phase % 2) == 0: # spoke_per_phase is even
                epsilon = alpha_ph/2
            elif (spoke_per_phase % 2) != 0:# spoke_per_phase is odd
                epsilon = alpha_ph/4
        else:
            if ( spoke_per_phase == 1 or  spoke_per_phase == 2):# we have 1 spoke for each phase
                epsilon = 0
            elif (int(spoke_per_phase/2) % 2) == 0: # spoke_per_phase/2 is even
                epsilon = alpha_ph/4
            elif (int(spoke_per_phase/2) % 2) != 0:# spoke_per_phase/2 is odd
                epsilon = alpha_ph/2

        # Shift of the angle if there is overlapping between spokes and the sector border
        #if ( int(self.Q/(2*self.m*self.t)) == float(self.Q/(2*self.m*self.t))):
            #epsilon = + alpha_ph /4;

        #epsilon = math.pi/30
        #print('spoke_per_phase '+str(spoke_per_phase))
        #print('SHIFT '+str(epsilon/math.pi*180))
        #print('alpha_se '+str(alpha_se/math.pi*180))
        #print('alpha_ph '+str(alpha_ph/math.pi*180))


        # First an array with all the angle and the sequence of label is create.
        #  Then the angle are sorted in order to achieve the correct sequence of spoke labels.
        #  At the same time, also the array of labels is sorted.
        for i in range(self.Q):         # Array creation
            s = spoke(i+1,alpha_se*i+epsilon);
            self.star.append(s);

        for i in range(self.Q):        # Makes all the angles in the rang [0 2*pi]
          while (self.star[i].angle>=2*math.pi):
              self.star[i].angle = self.star[i].angle - 2 * math.pi;
          if (abs(self.star[i].angle-2*math.pi) < 1e-4):
              self.star[i].angle = 0.0; # makes 0 the angle ~ 2pi

        # This should not be necessary since we use "angle_inside" function to test all the spokes
        # of the star without exploiting their order in the sequence
        #for i in range (self.Q):         # Sorting of the arrays
          #for j in range(i,self.Q):
            #if (self.star[i].angle < self.star[i].angle):
              #swap          = Spoke(self.star[i]);
              #self.star[i]  = self.star[j];
              #self.star[j]  = swap;


    def create_sectors(self,offset=0):

        self.p_sec.clear();
        self.n_sec.clear();

        for i in range(self.m): # Create the 2*m sectors
            if (self.m%2!=0): # Odd number of phases
                #start_angle = math.pi/self.m*(2*i-0.5)+offset;
                #end_angle   = math.pi/self.m*(2*i+0.5)+offset;
                #sec_p = sector(start_angle,end_angle);
                start_angle = offset + math.pi*0.5 + math.pi/self.m*(2*i-0.5);
                end_angle   = offset + math.pi*0.5 + math.pi/self.m*(2*i+0.5);
                sec_p = sector(start_angle,end_angle);
            else:  # even number of phases
                #start_angle = math.pi/self.m*(i-0.5)+offset;
                #end_angle   = math.pi/self.m*(i+0.5)+offset;
                #sec_p = sector(start_angle,end_angle);
                start_angle = offset + math.pi*0.5 + math.pi/self.m*(i-0.5);
                end_angle = offset + math.pi*0.5 + math.pi/self.m*(i+0.5);
                sec_p = sector(start_angle,end_angle);

            sec_p.normalize_angles();
            self.p_sec.append(sec_p); # positive
            sec_n = sector(start_angle+math.pi,end_angle+math.pi);
            sec_n.normalize_angles();
            self.n_sec.append(sec_n); # negative

        for i in range(len(self.star)): # Populate the sectors with the slots number
            # Check for positive sectors
            for j in range(len(self.p_sec)):
                if (self.p_sec[j].angle_inside(self.star[i].angle)):
                    self.p_sec[j].slots.append(self.star[i].id);
            for j in range(len(self.n_sec)):
                if (self.n_sec[j].angle_inside(self.star[i].angle)):
                    self.n_sec[j].slots.append(self.star[i].id);

    def gcd(self,a,b):
        if(b==0):
            return a
        else:
            return self.gcd(b,a%b)


    def populate_winding(self, win, _yq=-1, single_layer=False):

        if _yq < 0:
            yq = self.yq
        else:
            yq = _yq

        if (self.single_layer_feasible == False):
            single_layer = False;
        if (single_layer and (yq %2 == 0 )):
            yq = yq-1 # yq must be odd

        win.clear(); # clear all previous data

        nc = 1; # default number of conductors

        for i in range(self.m):
            w = winding(self.Q, self.p);
            # Add the coils of the positive sectors
            for j in range(len(self.p_sec[i].slots)):
                if (single_layer and (self.p_sec[i].slots[j]%2==0) ):
                    continue;
                end = self.p_sec[i].slots[j]+yq;
                while (end  > self.Q):
                    end -= self.Q;
                c = coil(self.p_sec[i].slots[j], end, nc);
                w.add_coil(c);
            # Add the coils of the negative sectors
            for j in range(len(self.n_sec[i].slots)):
                if (single_layer and (self.n_sec[i].slots[j]%2==0) ):
                    continue;
                end = self.n_sec[i].slots[j]+yq;
                while (end  > self.Q):
                    end -= self.Q;
                c = coil(self.n_sec[i].slots[j], end, -nc);
                w.add_coil(c);
            win.add_winding(w);

    def plot(self):
        """ plot the star of slots using matplotlib.pyplot."""
        _, ax = plt.subplots()

        ax = plt.axes()

        # some standard color according to resistance color code
        Y = ['brown','red','orange', 'yellow','green','blue', 'violet','gray']

        for i,sector in enumerate(self.p_sec):
            x1 = 1.0*math.cos(sector.start_angle)
            y1 = 1.0*math.sin(sector.start_angle)
            x2 = 1.0*math.cos(sector.end_angle)
            y2 = 1.0*math.sin(sector.end_angle)
            X = np.array([[x1,y1], [0,0], [x2, y2]])
            t1 = plt.Polygon(X[:3,:], color=Y[i])
            plt.gca().add_patch(t1)
        for i,sector in enumerate(self.n_sec):
            x1 = 0.8*math.cos(sector.start_angle)
            y1 = 0.8*math.sin(sector.start_angle)
            x2 = 0.8*math.cos(sector.end_angle)
            y2 = 0.8*math.sin(sector.end_angle)
            X = np.array([[x1,y1], [0,0], [x2, y2]])
            t1 = plt.Polygon(X[:3,:], color=Y[i])
            plt.gca().add_patch(t1)

        #for spoke in self.star:
            #x = math.cos(spoke.angle)
            #y = math.sin(spoke.angle)
            #ax.arrow(0, 0, x, y,head_width=0.05, head_length=0.1,
                     #fc='k', ec='k')
            #x = 1.2*math.cos(spoke.angle)
            #y = 1.2*math.sin(spoke.angle)
            #ax.annotate(str(spoke.id), xy=(x, y))
        for ii in range(int(self.Q/self.t)):
            spoke = self.star[ii]
            x = math.cos(spoke.angle)
            y = math.sin(spoke.angle)
            ax.arrow(0, 0, x, y,head_width=0.05, head_length=0.1,
                     fc='k', ec='k')
            x = 1.2*math.cos(spoke.angle)
            y = 1.2*math.sin(spoke.angle)
            ax.annotate(str(spoke.id), xy=(x, y))




        ax.margins(0.05)
        ax.axis('equal')
        plt.show()



class m_phase_winding():
    def __init__ (self):
        self.windings = []
        self.star = None
        self.p    = None # in general the winding has not predefined poles number
        self.slot_cur_matrix = []

    def add_winding(self,win):
        """
        Manually add a phase (a set of coils) to the m-phase winding
        """
        self.windings.append(win)

    def compute_winding(self,m,Q,p,yq=-1,single_layer=False):
        """
        Compute (and populate) a symmetrical and balanced winding on the basis of star of slot theory
        """

        self.p    = p # here we design for specific poles number
        self.slot_cur_matrix = np.zeros(Q)
        self.star = star_of_slot(m, Q, p);
        self.star.create_sectors();
        self.star.populate_winding(self,yq,single_layer);

    def clear(self):
        self.windings.clear()

    def fill_slot_cur_matrix(self,cur = []):

        # clear the previous values
        Q = len(self.slot_cur_matrix)
        if Q==0: # this can happen when we build a custom winding
            Q = self.windings[0].Q
        self.slot_cur_matrix = np.zeros(Q)

        m = len(self.windings) # the number of phases
        if len(cur) < m: # define default current values
            print('  KOIL WARNING: not enough current values provided')
            print('                Default values are adopted.')
            if (m % 2) == 0:
                # even number of phases
                cur = np.array([math.cos(math.pi/m*i) for i in range(m)])
            else:
                # odd number of phases
                cur = np.array([math.cos(2*math.pi/m*i) for i in range(m)])
            # print('KOIL: used current: '+str(cur))

        for i,w in enumerate(self.windings):
            sm = w.get_slot_matrix(normalize=True)
            # print('sm= '+str(sm))
            # print('self.slot_cur_matrix= '+str(self.slot_cur_matrix))
            self.slot_cur_matrix += sm * cur[i]

        return


    def calc_harmonics(self, D, nu_max = 100, ws = 0, cur = []):
        """
        Calculate the electric loading and mmf harmonics of the winding
        for a given set of current
        Parameters:
        -----------
        D:       stator airgap diameter
        nu_max:  how many harmonics to include in the computation (default 100)
        ws:      slot opening width
        cur:     the current values to be used for the computation (m values)

        """

        m = len(self.windings) # the number of phases
        if m==0: # check if data have been inserted
            print('  KOIL ERROR: please fill the winding before compute mmf harmonics!')
            exit()

        # fill the slots with the given current
        self.fill_slot_cur_matrix(cur)

        # compute the electric loading harmonics
        # TODO insert equation used here
        # compute a as: a_{\nu} = \dfrac{2}{\pi D} \int_0^C K(x) \cos \dfrac{2 \nu x}{\pi D} dx

        Q = len(self.slot_cur_matrix)

        if ws > math.pi*D/Q:

            print(' Unfeasible slot width, ws>pi*D/Q')

        else:

            a = []
            for nu in range(nu_max):
                _sum = 0;
                for j in range(Q):
                    _sum += self.slot_cur_matrix[j]  * math.cos(nu*2*math.pi/Q*(j+0.5));

                if ws == 0 :
                    _sum = _sum * 2/(math.pi*D)
                else:
                    _sum = _sum * 2/(math.pi*nu*ws)*math.sin(nu*ws/D);

                if (math.fabs(_sum) > 1e-5):
                    a.append(_sum);
                else:
                    a.append(0);

            # compute b as: b_{\nu} = \dfrac{2}{\pi D} \int_0^C K(x) \sin \dfrac{2 \nu x}{\pi D} dx

            b = []
            for nu in range(nu_max):
                _sum = 0;
                for j in range(Q):
                    _sum += self.slot_cur_matrix[j]  * math.sin(nu*2*math.pi/Q*(j+0.5));

                if ws == 0 :
                    _sum = _sum * 2/(math.pi*D)
                else:
                    _sum = _sum * 2/(math.pi*nu*ws)*math.sin(nu*ws/D);

                if (math.fabs(_sum) > 1e-5):
                    b.append(_sum);
                else:
                    b.append(0);

            # phi = []
            # c = []
            # for nu in range(nu_max):
            #     if a[nu] == 0:
            #         phi.append(0)
            #         c.append(0)
            #     else:
            #         phi.append(math.atan2(a[nu],b[nu]))
            #         c.append(a[nu]/math.sin(phi[nu]))

            phi = []
            c = []
            for nu in range(nu_max):
                if b[nu] == 0:
                    phi.append(-math.pi/2)
                    c.append(a[nu])
                else:
                    phi.append(math.atan2(a[nu],b[nu]))
                    c.append(b[nu]/math.cos(phi[nu]))

            d =[]
            for nu in range(nu_max):
                if nu == 0:
                    d.append(0)
                else:
                    d.append(-D/2*c[nu]/nu)

            # complex coefficients
            #e = []
            #for nu in range(nu_max):
                #_sum = 0;
                #for j in range(Q):
                    #_sum += self.slot_cur_matrix[j]  * -cmath.exp(nu*2*math.pi/Q*(j+0.5)*1j);

                #if ws == 0 :
                    #_sum = _sum * 1/(math.pi*D)
                #else:
                    #_sum = _sum * 1/(math.pi*nu*ws)*math.sin(nu*ws/D);

                #if (math.fabs(_sum) > 1e-5):
                    #e.append(_sum);
                #else:
                    #e.append(0);


            return a,b,c,phi,d
            #return a,b,c,phi,d,e

# TODO:
        # compute harmonics amplitude
        # consider the possibility to have custom angles!

    def calc_mmf(self, cur = []):
        """
        Compute the mmf diagram as a step waveform on the slots

        """


       # fill the slots with the given current
        self.fill_slot_cur_matrix(cur)

        mmf = [];
        x = [];
   #  QVector<QPointF> K;
   #
   #
   #  vector<double> slot_cur_matrix = win.Get_slot_cur_matrix();
   #
   #  K.push_back(QPointF(0,0));
   #  mmf.push_back(QPointF(0,0));
   #
        Q = len(self.slot_cur_matrix)
        D = 1
        ws = 1e-3
        ps = math.pi * D / Q;

        mmf_temp = 0;
        int_mmf  = 0;
   #
    # for(int i=0; i<Q; ++i):
        for i in range (Q):
        # i = 0,1,...,Q-1
   #     K.push_back(QPointF((ps-ws)/2 + ps*i,0));
   #
            x.append( (ps-ws)/2 + ps*i  );
            mmf.append(  mmf_temp  );
   #
   #     K.push_back(QPointF((ps-ws)/2 + ps*i,slot_cur_matrix[i] / ws));
   #
   #     K.push_back(QPointF((ps+ws)/2 + ps*i,slot_cur_matrix[i] / ws));
   #
   #     K.push_back(QPointF((ps+ws)/2 + ps*i,0));
   #
            mmf_temp += self.slot_cur_matrix[i];
            x.append( (ps+ws)/2 + ps*i  );
            mmf.append(  mmf_temp  );
            # mmf.append( [ (ps+ws)/2 + ps*i , mmf_temp ] );
   #
            int_mmf += (mmf_temp);

        print(mmf)

        _mmf = [ m-int_mmf/Q for m in mmf]

        print(_mmf)
        return x , _mmf
