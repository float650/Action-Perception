import numpy as np
from matplotlib import pyplot as pp

import math

import theano
import theano.tensor as T

from theano.sandbox.rng_mrg import MRG_RandomStreams as RandomStreams

class SLmodel():
	
	#This is the switched conditional linear model for integrating 
	#action with sensation
	
	def __init__(self, nx, ns, nh, na, npcl, xvar=1.0):
		
		#for this model I assume one linear generative model and a 
		#combination of nh linear dynamical models
		
		#generative matrix
		init_W=np.asarray(np.random.randn(nx,ns)/10.0,dtype='float32')
		
		#observed variable means
		init_c=np.asarray(np.zeros(nx),dtype='float32')
		
		#dynamical matrices
		init_M=np.asarray((np.tile(np.eye(ns),(1,nh))),dtype='float32')  #for state-based predictions
		init_C=np.asarray((np.tile(np.zeros((na,ns)),(1,nh))),dtype='float32')  #for action-based predictions
		
		#state-variable variances
		#(covariance matrix of state variable noise assumed to be diagonal)
		init_b=np.asarray(np.ones(ns)*10.0,dtype='float32')
		
		#Switching parameter matrices
		init_A=np.asarray(np.zeros((ns,nh)),dtype='float32') #associated with the state
		init_B=np.asarray(np.zeros((na,nh)),dtype='float32') #associated with actions
		
		#priors for switching variable
		init_ph=np.asarray(np.zeros(nh),dtype='float32')
		
		init_s_now=np.asarray(np.zeros((npcl,ns)),dtype='float32')
		init_weights_now=np.asarray(np.ones(npcl)/float(npcl),dtype='float32')
		
		init_s_past=np.asarray(np.zeros((npcl,ns)),dtype='float32')
		init_h_past=np.asarray(np.zeros((npcl,nh)),dtype='float32')
		init_h_past[:,0]=1.0
		init_weights_past=np.asarray(np.ones(npcl)/float(npcl),dtype='float32')
		
		init_a_past=np.asarray(np.zeros((1,na)),dtype='float32')
		
		self.W=theano.shared(init_W)
		self.c=theano.shared(init_c)
		self.M=theano.shared(init_M)
		self.C=theano.shared(init_C)
		self.b=theano.shared(init_b)
		self.A=theano.shared(init_A)
		self.B=theano.shared(init_B)
		self.ph=theano.shared(init_ph)
		
		#this is to help vectorize operations
		self.sum_mat=T.as_tensor_variable(np.asarray((np.tile(np.eye(ns),nh)).T,dtype='float32'))
		
		self.s_now=theano.shared(init_s_now)
		self.weights_now=theano.shared(init_weights_now)
		
		self.s_past=theano.shared(init_s_past)
		self.h_past=theano.shared(init_h_past)
		self.a_past=theano.shared(init_a_past)
		self.weights_past=theano.shared(init_weights_past)
		
		self.xvar=np.asarray(xvar,dtype='float32')
		
		self.nx=nx		#dimensionality of observed variables
		self.ns=ns		#dimensionality of latent variables
		self.nh=nh		#number of (linear) dynamical modes
		self.na=na		#dimensionality of action variables
		self.npcl=npcl	#numer of particles in particle filter
		
		self.theano_rng = RandomStreams()
		
		self.params=				[self.W, self.M, self.C, self.b, self.A, self.B, self.c, self.ph]
		self.rel_lrates=np.asarray([  0.1,    1.0,    1.0,    0.01,   10.0,    10.0,  0.1,     1.0]   ,dtype='float32')
	
	
	def sample_proposal_s(self, s, a, h, xpred, sig):
		
		s_pred=self.get_prediction(s, a, h)
		
		n=self.theano_rng.normal(size=T.shape(s))
		
		#This is the proposal distribution that arises when one assumes that W'W=I
		
		mean=2.0*(xpred+s_pred*(self.b**2))*sig
		
		s_prop=mean+n*T.sqrt(sig)
		
		#I compute the term inside the exponent for the pdf of the proposal distrib
		prop_term=-T.sum(n**2)/2.0
		
		return T.cast(s_prop,'float32'), T.cast(s_pred,'float32'), T.cast(prop_term,'float32')
	
	
	#This function is required if we allow multiple generative models
	
	#def get_recon(self, s, h):
		
		#W_vec=T.sum(self.W*h, axis=0)
		#W=W.reshape((self.nx, self.ns))
		
		#xr=T.dot(W, s)
		
		#return xr
	
	
	def calc_h_probs(self, s, a):
		
		#this function takes an np by ns matrix of s samples plus
		#an action vector a
		#and returns an nh by np set of h probabilities
		
		exp_terms=T.dot(s, self.A)+ T.reshape(T.dot(a, self.B),(1,self.nh)) + T.reshape(self.ph,(1,self.nh))
		
		#re-centering for numerical stability
		exp_terms_recentered=exp_terms-T.max(exp_terms,axis=1)
		
		#exponentiation and normalization
		rel_probs=T.exp(exp_terms)
		probs=rel_probs.T/T.sum(rel_probs, axis=1)
		
		return probs.T
	
		
	
	def forward_filter_step(self, a, xp):
		
		#first sample from h given s and a
		
		h_probs = self.calc_h_probs(self.s_now, a)
		h_samps=self.theano_rng.multinomial(pvals=h_probs)
		
		#need to sample from the proposal distribution
		#these terms are the same for every particle
		xpred=T.dot(self.W.T,(xp-self.c))/(2.0*self.xvar**2)
		sig=(1.0/(self.b**2+1.0/(2.0*self.xvar**2)))/2.0
		
		#sig=1.0/(self.b**2)
		
		#vectorized version
		s_pred=self.get_prediction(self.s_now, a, h_samps)
		
		n=self.theano_rng.normal(size=T.shape(self.s_now))
		
		mean=2.0*(xpred+s_pred*(self.b**2))*sig
		
		#mean=s_pred  #trying out using solely predictive proposal distrib
		
		s_samps=mean+n*T.sqrt(sig)
		
		prop_terms=-T.sum(n**2,axis=1)/2.0
		
		updates={}
		
		#now that we have samples from the proposal distribution, we need to reweight them
		
		recons=T.dot(self.W, s_samps.T) + T.reshape(self.c,(self.nx,1))
		
		x_terms=-T.sum((recons-T.reshape(xp,(self.nx,1)))**2,axis=0)/(2.0*self.xvar**2)
		s_terms=-T.sum(((s_samps-s_pred)*self.b)**2,axis=1)/2.0
		
		energies=x_terms+s_terms-prop_terms
		
		#to avoid exponentiating large or very small numbers, I 
		#"re-center" the reweighting factors by adding a constant, 
		#as this has no impact on the resulting new weights
		
		energies_recentered=energies-T.max(energies)
		
		alpha=T.exp(energies_recentered) #these are the reweighting factors
		
		new_weights_unnorm=self.weights_now*alpha
		normalizer=T.sum(new_weights_unnorm)
		new_weights=new_weights_unnorm/normalizer  #need to normalize new weights
		
		updates[self.h_past]=T.cast(h_samps,'float32')
		updates[self.s_past]=T.cast(self.s_now,'float32')
		updates[self.a_past]=T.cast(a,'float32')
		updates[self.s_now]=T.cast(s_samps,'float32')
		
		updates[self.weights_past]=T.cast(self.weights_now,'float32')
		updates[self.weights_now]=T.cast(new_weights,'float32')
		
		#return normalizer, energies_recentered, s_samps, s_pred, T.dot(self.W.T,(xp-self.c)), updates
		#return normalizer, energies_recentered, updates
		#return h_samps, updates
		return updates
		
	
	def get_prediction(self, s, a, h):
		
		s_dot_M=T.dot(s, self.M)  #this is np by nh*ns
		a_dot_C=T.dot(a, self.C)  #this is 1 by nh*ns
		tot=s_dot_M+a_dot_C  #should be np by nh*ns
		s_pred=T.dot(tot*T.extra_ops.repeat(h,self.ns,axis=1),self.sum_mat) #should be np by ns
		
		return T.cast(s_pred,'float32')
	
	
	def sample_joint(self, sp):
		
		t2_samp=self.theano_rng.multinomial(pvals=T.reshape(self.weights_now,(1,self.npcl))).T
		s2_samp=T.cast(T.sum(self.s_now*T.addbroadcast(t2_samp,1),axis=0),'float32')
		h2_samp=T.cast(T.sum(self.h_now*T.addbroadcast(t2_samp,1),axis=0),'float32')
		
		diffs=self.b*(s2_samp-sp)
		sqr_term=T.sum(diffs**2,axis=1)
		alpha=T.exp(-sqr_term)
		probs_unnorm=self.weights_past*alpha
		probs=probs_unnorm/T.sum(probs_unnorm)
		
		t1_samp=self.theano_rng.multinomial(pvals=T.reshape(probs,(1,self.npcl))).T
		s1_samp=T.cast(T.sum(self.s_past*T.addbroadcast(t1_samp,1),axis=0),'float32')
		h1_samp=T.cast(T.sum(self.h_past*T.addbroadcast(t1_samp,1),axis=0),'float32')
		
		return [s1_samp, h1_samp, s2_samp, h2_samp]
	
	
	def calc_mean_h_energy(self, s, a, h):
		
		#you give this function a set of samples of s, a, and h,
		#it gives you the average energy of those samples
		
		exp_terms=T.dot(s, self.A)+ T.reshape(T.dot(a, self.B),(1,self.nh)) + T.reshape(self.ph,(1,self.nh))  #np by nh
		
		energies=T.sum(h*exp_terms,axis=1) - T.log(T.sum(T.exp(exp_terms),axis=1)) #should be np by 1
		
		energy=T.mean(energies)
		
		return energy
	
	
	def update_params(self, x1, x2, n_samps, lrate):
		
		#this function samples from the joint posterior and performs
		# a step of gradient ascent on the log-likelihood
		
		sp=self.get_prediction(self.s_past, self.a_past, self.h_past)
									
		#sp should be np by ns
		
		
		[s1_samps, h1_samps, s2_samps, h2_samps], updates = theano.scan(fn=self.sample_joint,
									outputs_info=[None, None, None, None],
									non_sequences=[sp],
									n_steps=n_samps)
		
		
		
		x1_recons=T.dot(self.W, s1_samps.T) + T.reshape(self.c,(self.nx,1))
		x2_recons=T.dot(self.W, s2_samps.T) + T.reshape(self.c,(self.nx,1))
		
		s_pred = self.get_prediction(s1_samps, h1_samps)
		
		
		hterm1=self.calc_mean_h_energy(s1_samps, h1_samps)
		#hterm2=self.calc_mean_h_energy(s2_samps, h2_samps)
		
		sterm=-T.mean(T.sum((self.b*(s2_samps-s_pred))**2,axis=1))/2.0
		
		xterm1=-T.mean(T.sum((x1_recons-T.reshape(x1,(self.nx,1)))**2,axis=0)/(2.0*self.xvar**2))
		xterm2=-T.mean(T.sum((x2_recons-T.reshape(x2,(self.nx,1)))**2,axis=0)/(2.0*self.xvar**2))
		
		#energy = hterm1 + xterm1 + hterm2 + xterm2 + sterm -T.sum(T.sum(self.A**2))
		energy = hterm1 + xterm1 + xterm2 + sterm 
		
		gparams=T.grad(energy, self.params, consider_constant=[s1_samps, s2_samps, h1_samps, h2_samps])
		
		# constructs the update dictionary
		for gparam, param, rel_lr in zip(gparams, self.params, self.rel_lrates):
			#gnat=T.dot(param, T.dot(param.T,param))
			updates[param] = T.cast(param + gparam*lrate*rel_lr,'float32')
		
		
		#make sure W has unit-length columns
		#new_W=updates[self.W]
		#updates[self.W]=T.cast(new_W/T.sqrt(T.sum(new_W**2,axis=0)),'float32')
		
		#MIGHT NEED TO NORMALIZE A
		
		
		return energy, updates
		
	
	def get_ESS(self):
		
		return 1.0/T.sum(self.weights_now**2)
	
	
	def resample_step(self):
		
		idx=self.theano_rng.multinomial(pvals=T.reshape(self.weights_now,(1,self.npcl))).T
		s_samp=T.sum(self.s_now*T.addbroadcast(idx,1),axis=0)
		h_samp=T.sum(self.h_now*T.addbroadcast(idx,1),axis=0)
		
		return T.cast(s_samp,'float32'), T.cast(h_samp,'float32')
	
	
	def resample(self):
		
		[s_samps, h_samps], updates = theano.scan(fn=self.resample_step,
												outputs_info=[None, None],
												n_steps=self.npcl)
		
		updates[self.s_now]=T.cast(s_samps,'float32')
		updates[self.h_now]=T.cast(h_samps,'float32')
		updates[self.weights_now]=T.cast(T.ones_like(self.weights_now)/T.cast(self.npcl,'float32'),'float32') #dtype paranoia
		
		return updates
	
	
	def simulate_step(self, s, a):
		
		s=T.reshape(s,(1,self.ns))
		a=T.reshape(a,(1,self.na))
		#get h probabilities
		h_probs = self.calc_h_probs(s,a)
		h_samp=self.theano_rng.multinomial(pvals=h_probs)
		
		sp=self.get_prediction(s,a,h_samp)
		
		xp=T.dot(self.W, sp.T) + T.reshape(self.c,(self.nx,1))
		
		return T.cast(sp,'float32'), T.cast(xp,'float32'), h_samp
		
	
	def simulate_forward(self, a, n_steps):
		
		#a should be n_steps by na
		
		s0=T.sum(self.s_now*T.reshape(self.weights_now,(self.npcl,1)),axis=0)
		s0=T.reshape(s0,(1,self.ns))
		[sp, xp, hs], updates = theano.scan(fn=self.simulate_step,
										outputs_info=[s0, None, None],
										sequences=[a],
										n_steps=n_steps)
		
		return sp, xp, hs, updates

'''

nx=2
ns=2
nh=2
npcl=20

nsamps=10
lrate=1e-3

model=SCLmodel(nx, ns, nh, npcl, xvar=0.1)


x=T.fvector()

#norm, eng, ssmp, sprd, Wx, updates0=model.forward_filter_step(x)
#norm, eng, updates0=model.forward_filter_step(x)
#inference_step=theano.function([x],[norm,eng,ssmp,sprd,Wx],updates=updates0,allow_input_downcast=True)
#inference_step=theano.function([x],[norm,eng],updates=updates0,allow_input_downcast=True)
hsmps, updates0=model.forward_filter_step(x)
inference_step=theano.function([x],hsmps,updates=updates0,allow_input_downcast=True)

ess=model.get_ESS()
get_ESS=theano.function([],ess)

updates1=model.resample()
resample=theano.function([],updates=updates1)

x1=T.fvector(); x2=T.fvector()
lr=T.fscalar(); nsmps=T.lscalar()

nrg, updates2 = model.update_params(x1, x2, nsmps, lr)
learn_step=theano.function([x1,x2,nsmps,lr],[nrg],updates=updates2,allow_input_downcast=True)

nps=T.lscalar()
sps, xps, hs, updates3 = model.simulate_forward(nps)
predict=theano.function([nps],[sps,xps,hs],updates=updates3,allow_input_downcast=True)

theta=0.2
vec=np.ones(2)
M1=np.asarray([[np.cos(theta),-np.sin(theta)],[np.sin(theta),np.cos(theta)]],dtype='float32')
M2=np.asarray([[np.cos(theta/3.0),-np.sin(theta/3.0)],[np.sin(theta/3.0),np.cos(theta/3.0)]],dtype='float32')
W=np.asarray(np.random.randn(2,2),dtype='float32')
c=np.asarray(np.random.randn(2),dtype='float32')

dt=0.05
nt=100000


x_hist=[]
h_hist=[]
v_hist=[]
e_hist=[]
s_hist=[]
r_hist=[]
l_hist=[]
w_hist=[]

resample_counter=0
learn_counter=0

for i in range(nt):
	if vec[0]+np.random.randn(1)/100.0>0:
		M=M1
	else:
		M=M2
	vec=np.dot(M,vec)+np.random.randn(2)*0.01
	x=np.dot(W,vec)+c+np.random.randn(2)*0.1
	v_hist.append(vec)
	x_hist.append(x)
	
	#normalizer,energies,ssamps,spreds,WTx=inference_step(vec)
	#normalizer,energies=inference_step(x)
	h_samps=inference_step(x)
	
	#pp.scatter(ssamps[:,0],ssamps[:,1],color='b')
	#pp.scatter(spreds[:,0],spreds[:,1],color='r')
	#pp.scatter(WTx[0],WTx[1],color='g')
	
	#pp.hist(energies,20)
	#pp.show()
	
	#print h_samps
	
	ESS=get_ESS()
	
	learn_counter+=1
	resample_counter+=1
	
	if resample_counter>0 and learn_counter>20:
		
		energy=learn_step(x_hist[-2],x_hist[-1],nsamps, lrate)
		e_hist.append(energy)
		learn_counter=0
		l_hist.append(1)
		lrate=lrate*0.9993094
	else:
		l_hist.append(0)
	
	if i%1000==0:	
		#print normalizer
		print ESS
		print i
		print model.M.get_value()
		print model.W.get_value()
		print model.A.get_value()
		print model.mu.get_value()
		print model.c.get_value()
		print model.b.get_value()
	if ESS<npcl/2:
		resample()
		resample_counter=0
		r_hist.append(1)
	else:
		r_hist.append(0)
	
	s_hist.append(model.s_now.get_value())
	w_hist.append(model.weights_now.get_value())
	h_hist.append(model.h_now.get_value())
	
	if math.isnan(ESS):
		print model.b.get_value()
		print model.M.get_value()
		print model.W.get_value()
		break



xact=[]

npred=1000


for i in range(npred):
	if vec[0]+np.random.randn(1)/100.0>0:
		M=M1
	else:
		M=M2
	vec=np.dot(M,vec)+np.random.randn(2)*np.sqrt(0.0001)
	x=np.dot(W,vec)+c+np.random.randn(2)*np.sqrt(0.01)
	xact.append(x)

xact=np.asarray(xact)

spred, xpred, hsmps = predict(npred)



s_hist=np.asarray(s_hist)
w_hist=np.asarray(w_hist)
h_hist=np.asarray(h_hist)
s_av=np.mean(s_hist,axis=1)
print s_hist.shape
print h_hist.shape

h_hist=h_hist*np.asarray([0,1])
h_av=np.mean(h_hist,axis=2)
h_av=np.mean(h_hist,axis=1)


v_hist=np.asarray(v_hist)
x_hist=np.asarray(x_hist)
e_hist=np.asarray(e_hist)
l_hist=np.asarray(l_hist)-.5
r_hist=np.asarray(r_hist)-.5
pp.plot(x_hist)
pp.figure(2)
pp.plot(v_hist)
pp.figure(3)
pp.plot(e_hist)
pp.figure(4)
pp.plot(s_av)
#pp.plot(r_hist, 'r')
#pp.plot(l_hist, 'k')

pp.figure(5)
for i in range(npcl):
	pp.scatter(range(len(s_hist)),s_hist[:,i,0],color=zip(w_hist[:,i],np.zeros(len(w_hist)),1.0-w_hist[:,i]))

pp.figure(6)
for i in range(npcl):
	pp.scatter(range(len(s_hist)),s_hist[:,i,1],color=zip(w_hist[:,i],np.zeros(len(w_hist)),1.0-w_hist[:,i]))
	
pp.figure(7)
for i in range(npcl):
	pp.scatter(range(len(s_hist)),s_hist[:,i,0],color=zip(np.ones(len(w_hist)),np.zeros(len(w_hist)),np.zeros(len(w_hist)),w_hist[:,i]))



#pp.figure(6)
#pp.plot(h_av)

#pp.figure(7)
#pp.plot(spred)

#pp.figure(8)
#pp.plot(xpred,'r')
#pp.plot(xact,'b')



#pp.figure(6)
#for i in range(npcl):
	#pp.scatter(range(len(s_hist)),s_hist[:,i,0],c='k',s=5)

#pp.figure(5)
#for i in range(npcl):
	#pp.scatter(range(len(s_hist)),s_hist[:,i,1],color=zip(np.zeros(len(w_hist)),np.zeros(len(w_hist)),np.ones(len(w_hist)),w_hist[:,i]))


pp.show()



'''



