# -*- coding: utf-8 -*-
"""Assignment4DLL.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1dOY3ZF2joF4gWO0cC0HofTxeNWMbwILK
"""

#@title
import numpy as np
import os
os.environ.setdefault('PATH', '')
from collections import deque
import gym
from gym import spaces
import cv2
cv2.ocl.setUseOpenCL(False)

class TimeLimit(gym.Wrapper):
    def __init__(self, env, max_episode_steps=None):
        super(TimeLimit, self).__init__(env)
        self._max_episode_steps = max_episode_steps
        self._elapsed_steps = 0

    def step(self, ac):
        observation, reward, done, info = self.env.step(ac)
        self._elapsed_steps += 1
        if self._elapsed_steps >= self._max_episode_steps:
            done = True
            info['TimeLimit.truncated'] = True
        return observation, reward, done, info

    def reset(self, **kwargs):
        self._elapsed_steps = 0
        return self.env.reset(**kwargs)

class ClipActionsWrapper(gym.Wrapper):
    def step(self, action):
        import numpy as np
        action = np.nan_to_num(action)
        action = np.clip(action, self.action_space.low, self.action_space.high)
        return self.env.step(action)

    def reset(self, **kwargs):
        return self.env.reset(**kwargs)

class NoopResetEnv(gym.Wrapper):
    def __init__(self, env, noop_max=30):
        """Sample initial states by taking random number of no-ops on reset.
        No-op is assumed to be action 0.
        """
        gym.Wrapper.__init__(self, env)
        self.noop_max = noop_max
        self.override_num_noops = None
        self.noop_action = 0
        assert env.unwrapped.get_action_meanings()[0] == 'NOOP'

    def reset(self, **kwargs):
        """ Do no-op action for a number of steps in [1, noop_max]."""
        self.env.reset(**kwargs)
        if self.override_num_noops is not None:
            noops = self.override_num_noops
        else:
            noops = self.unwrapped.np_random.randint(1, self.noop_max + 1) #pylint: disable=E1101
        assert noops > 0
        obs = None
        for _ in range(noops):
            obs, _, done, _ = self.env.step(self.noop_action)
            if done:
                obs = self.env.reset(**kwargs)
        return obs

    def step(self, ac):
        return self.env.step(ac)

class FireResetEnv(gym.Wrapper):
    def __init__(self, env):
        """Take action on reset for environments that are fixed until firing."""
        gym.Wrapper.__init__(self, env)
        assert env.unwrapped.get_action_meanings()[1] == 'FIRE'
        assert len(env.unwrapped.get_action_meanings()) >= 3

    def reset(self, **kwargs):
        self.env.reset(**kwargs)
        obs, _, done, _ = self.env.step(1)
        if done:
            self.env.reset(**kwargs)
        obs, _, done, _ = self.env.step(2)
        if done:
            self.env.reset(**kwargs)
        return obs

    def step(self, ac):
        return self.env.step(ac)

class EpisodicLifeEnv(gym.Wrapper):
    def __init__(self, env):
        """Make end-of-life == end-of-episode, but only reset on true game over.
        Done by DeepMind for the DQN and co. since it helps value estimation.
        """
        gym.Wrapper.__init__(self, env)
        self.lives = 0
        self.was_real_done  = True

    def step(self, action):
        obs, reward, done, info = self.env.step(action)
        self.was_real_done = done
        # check current lives, make loss of life terminal,
        # then update lives to handle bonus lives
        lives = self.env.unwrapped.ale.lives()
        if lives < self.lives and lives > 0:
            # for Qbert sometimes we stay in lives == 0 condition for a few frames
            # so it's important to keep lives > 0, so that we only reset once
            # the environment advertises done.
            done = True
        self.lives = lives
        return obs, reward, done, info

    def reset(self, **kwargs):
        """Reset only when lives are exhausted.
        This way all states are still reachable even though lives are episodic,
        and the learner need not know about any of this behind-the-scenes.
        """
        if self.was_real_done:
            obs = self.env.reset(**kwargs)
        else:
            # no-op step to advance from terminal/lost life state
            obs, _, _, _ = self.env.step(0)
        self.lives = self.env.unwrapped.ale.lives()
        return obs

class MaxAndSkipEnv(gym.Wrapper):
    def __init__(self, env, skip=4):
        """Return only every `skip`-th frame"""
        gym.Wrapper.__init__(self, env)
        # most recent raw observations (for max pooling across time steps)
        self._obs_buffer = np.zeros((2,)+env.observation_space.shape, dtype=np.uint8)
        self._skip       = skip

    def step(self, action):
        """Repeat action, sum reward, and max over last observations."""
        total_reward = 0.0
        done = None
        for i in range(self._skip):
            obs, reward, done, info = self.env.step(action)
            if i == self._skip - 2: self._obs_buffer[0] = obs
            if i == self._skip - 1: self._obs_buffer[1] = obs
            total_reward += reward
            if done:
                break
        # Note that the observation on the done=True frame
        # doesn't matter
        max_frame = self._obs_buffer.max(axis=0)

        return max_frame, total_reward, done, info

    def reset(self, **kwargs):
        return self.env.reset(**kwargs)

class ClipRewardEnv(gym.RewardWrapper):
    def __init__(self, env):
        gym.RewardWrapper.__init__(self, env)

    def reward(self, reward):
        """Bin reward to {+1, 0, -1} by its sign."""
        return np.sign(reward)


class WarpFrame(gym.ObservationWrapper):
    def __init__(self, env, width=84, height=84, grayscale=True, dict_space_key=None):
        """
        Warp frames to 84x84 as done in the Nature paper and later work.
        If the environment uses dictionary observations, `dict_space_key` can be specified which indicates which
        observation should be warped.
        """
        super().__init__(env)
        self._width = width
        self._height = height
        self._grayscale = grayscale
        self._key = dict_space_key
        if self._grayscale:
            num_colors = 1
        else:
            num_colors = 3

        new_space = gym.spaces.Box(
            low=0,
            high=255,
            shape=(self._height, self._width, num_colors),
            dtype=np.uint8,
        )
        if self._key is None:
            original_space = self.observation_space
            self.observation_space = new_space
        else:
            original_space = self.observation_space.spaces[self._key]
            self.observation_space.spaces[self._key] = new_space
        assert original_space.dtype == np.uint8 and len(original_space.shape) == 3

    def observation(self, obs):
        if self._key is None:
            frame = obs
        else:
            frame = obs[self._key]

        if self._grayscale:
            frame = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
        frame = cv2.resize(
            frame, (self._width, self._height), interpolation=cv2.INTER_AREA
        )
        if self._grayscale:
            frame = np.expand_dims(frame, -1)

        if self._key is None:
            obs = frame
        else:
            obs = obs.copy()
            obs[self._key] = frame
        return obs


class FrameStack(gym.Wrapper):
    def __init__(self, env, k):
        """Stack k last frames.
        Returns lazy array, which is much more memory efficient.
        See Also
        --------
        baselines.common.atari_wrappers.LazyFrames
        """
        gym.Wrapper.__init__(self, env)
        self.k = k
        self.frames = deque([], maxlen=k)
        shp = env.observation_space.shape
        self.observation_space = spaces.Box(low=0, high=255, shape=(shp[:-1] + (shp[-1] * k,)), dtype=env.observation_space.dtype)

    def reset(self):
        ob = self.env.reset()
        for _ in range(self.k):
            self.frames.append(ob)
        return self._get_ob()

    def step(self, action):
        ob, reward, done, info = self.env.step(action)
        self.frames.append(ob)
        return self._get_ob(), reward, done, info

    def _get_ob(self):
        assert len(self.frames) == self.k
        return LazyFrames(list(self.frames))

class ScaledFloatFrame(gym.ObservationWrapper):
    def __init__(self, env):
        gym.ObservationWrapper.__init__(self, env)
        self.observation_space = gym.spaces.Box(low=0, high=1, shape=env.observation_space.shape, dtype=np.float32)

    def observation(self, observation):
        # careful! This undoes the memory optimization, use
        # with smaller replay buffers only.
        return np.array(observation).astype(np.float32) / 255.0

class LazyFrames(object):
    def __init__(self, frames):
        """This object ensures that common frames between the observations are only stored once.
        It exists purely to optimize memory usage which can be huge for DQN's 1M frames replay
        buffers.
        This object should only be converted to numpy array before being passed to the model.
        You'd not believe how complex the previous solution was."""
        self._frames = frames
        self._out = None

    def _force(self):
        if self._out is None:
            self._out = np.concatenate(self._frames, axis=-1)
            self._frames = None
        return self._out

    def __array__(self, dtype=None):
        out = self._force()
        if dtype is not None:
            out = out.astype(dtype)
        return out

    def __len__(self):
        return len(self._force())

    def __getitem__(self, i):
        return self._force()[i]

    def count(self):
        frames = self._force()
        return frames.shape[frames.ndim - 1]

    def frame(self, i):
        return self._force()[..., i]

def make_atari(env_id, max_episode_steps=None):
    env = gym.make(env_id)
    assert 'NoFrameskip' in env.spec.id
    env = NoopResetEnv(env, noop_max=30)
    env = MaxAndSkipEnv(env, skip=4)
    if max_episode_steps is not None:
        env = TimeLimit(env, max_episode_steps=max_episode_steps)
    return env

def wrap_deepmind(env, episode_life=True, clip_rewards=True, frame_stack=False, scale=False):
    """Configure environment for DeepMind-style Atari.
    """
    if episode_life:
        env = EpisodicLifeEnv(env)
    if 'FIRE' in env.unwrapped.get_action_meanings():
        env = FireResetEnv(env)
    env = WarpFrame(env)
    if scale:
        env = ScaledFloatFrame(env)
    if clip_rewards:
        env = ClipRewardEnv(env)
    if frame_stack:
        env = FrameStack(env, 4)
    return env

"""Input:
  - $N$: Number of steps
  - $M$: Replay Buffer Size
  - $\epsilon$ : Probability of random action
  - $\gamma$: Discount rate
  - $B$: Batch Size
  - $\alpha$: Learning Rate
  - $n$: Number of steps between online Q learning network updates
  - $C$: Number of steps between target Q-network updates 
Output:
-Estimate of $Q(.,\theta)$ of the optimal action value function $Q*$
---

`1:` Initialize replay buffer $\mathcal{D}$, which stores at most $M$ tuples <br>
`2:` Initialize network parameters $\theta$ randomly <br>
`3:` $\theta'=\theta$ <br>
`4:` $i=0$ <br>
`5:` while $i<N$: <br>
`6:` $\quad \quad $ $s_0 =$ inital state for the episode <br>
`7:` $\quad \quad$ for each $t$ in  $\{0, 1, 2...\}$:<br>
`8:` $\quad \quad \quad \quad$ if $random() < 1-\epsilon$: <br>
`9:` $\quad \quad \quad \quad \quad \quad$ $a_t=argmax_a Q(s_t,a, \theta)$ <br>
`10:` $\quad \quad \quad \quad$ else: <br>
`11:` $ \quad \quad \quad \quad \quad \quad$ $a_t= random \: action$ <br>
`12:` $\quad \quad \quad \quad$ if episode ends at step $t+1$: <br>
`13:` $\quad \quad \quad \quad \quad \quad$ $\Omega_{t+1}=1$   <br>
`14:` $\quad \quad \quad \quad$ else: <br>
`15:` $\quad \quad \quad \quad \quad \quad$ $\Omega_{t+1}=0$   <br>
`16:` $\quad \quad \quad \quad$ Store the tuple $(s_t, a_t, r_{t+1}, s_{t+1}, \Omega_{t+1})$ in the replay buffer $\mathcal{D}$   <br>
`17:` $\quad \quad \quad \quad$ $i+=1$ <br>
`18:` $\quad \quad \quad \quad$ if $i \ge M$: <br>
`19:` $\quad \quad \quad \quad \quad \quad$ if $i\%n==0:$ <br>
`20:` $\quad \quad \quad \quad \quad \quad \quad \quad$ Sample a subset $\mathcal{D'} \subset \mathcal{D}$ composed of $B$ tuples <br>
`21:` $\quad \quad \quad \quad \quad \quad \quad \quad$ $y=r+\gamma \max_{a'} Q(s',a', \theta')$ if $\: \Omega_{t+1}==1$ else $y=r$ <br>

`22:` $\quad \quad \quad \quad \quad \quad \quad \quad$ Let $L(\theta)= \Sigma_{(s_t, a_t, r_{t+1}, s_{t+1}, \Omega_{t+1}) \in \mathcal{D'}}(y-Q(s_t,a, \theta))^2$ <br>
`23:` $\quad \quad \quad \quad \quad \quad \quad \quad$ $\theta=\theta - \Delta_{\theta}L(\theta)$,  noting that $\theta′$ is considered a constant with respect to $\theta$<br>
`24:` $\quad \quad \quad \quad \quad \quad$ if $i\%C==0:$<br>
`25:` $\quad \quad \quad \quad \quad \quad \quad \quad$ $\theta'=\theta$<br>
`26:` $\quad \quad \quad \quad $ if $\Omega_{t+1}==1:$<br>
`27:` $\quad \quad \quad \quad \quad \quad$ break<br>

# Environment
"""

def wrap_atari_deepmind(environment_name='BreakoutNoFrameskip-v4',clipped_reward=False):
  env=make_atari(environment_name)
  wrapped_env=wrap_deepmind(env, episode_life=True, clip_rewards=clipped_reward, frame_stack=True, scale=True)
  #episode life=True, frame stack=True, scale=True, and clip rewards 
  #use make_atari to create the environment by name, and wrap the resulting environment with the wrap deepmind function
  return wrapped_env

env=wrap_atari_deepmind(clipped_reward=True)
env_eval=wrap_atari_deepmind()

"""# Agent
1. Online Q-network
2. Target Q-network
3. Replay buffer
"""

from collections import deque
import tensorflow as tf

class Agent:
  def __init__(self,env):
    self.replay_buffer=deque(maxlen=10000)
    self.actions=range(env.action_space.n)

def cal_epsilone(i):
  if i>1e6: return 0.1
  return 1-(0.9/1e6*i)

"""# Tensorflow Graph"""

tf.reset_default_graph()
#number of actions
k=env.action_space.n
n=4 #batch sampling
N=2e6
gamma=.99
C=1e4
learning_rate=0.0001
decay=0.99
M=1e4
eval_freq = 1e5
agent=Agent(env)

#NN Model Architecture Wrappers:
def conv_layer(input, weight_matrix, strides):
    input = tf.nn.conv2d(input, weight_matrix, strides=[1, strides, strides, 1], padding='SAME')
    return tf.nn.relu(input)

def fully_connected(input, Wout, bout, relu=False): 
  Z = tf.matmul(input, Wout) + bout
  if relu:
    return tf.nn.relu(Z)
  return Z

def dictionary_weights(dictionary, n, trainable):
  dictionary={'conv1':tf.get_variable(f"conv1_{n}", shape=[8,8,4,32], initializer=tf.contrib.layers.variance_scaling_initializer(), trainable=trainable, dtype=tf.float32),
      'conv2':tf.get_variable(f"conv2_{n}", shape=[4,4,32,64], initializer=tf.contrib.layers.variance_scaling_initializer(), trainable=trainable, dtype=tf.float32),
      'conv3':tf.get_variable(f"conv3_{n}", shape=[3,3,64,64], initializer=tf.contrib.layers.variance_scaling_initializer(), trainable=trainable, dtype=tf.float32),
      'fc1_w':tf.get_variable(f"fc1_w_{n}", shape=[11*11*64,512], initializer=tf.contrib.layers.variance_scaling_initializer(), trainable=trainable, dtype=tf.float32),
      'fc1_b':tf.get_variable(f"fc1_b_{n}", shape=[512], initializer=tf.zeros_initializer(), trainable=trainable, dtype=tf.float32),
      'fc2_w':tf.get_variable(f"fc2_w_{n}", shape=[512, 4], initializer=tf.contrib.layers.variance_scaling_initializer(), trainable=trainable, dtype=tf.float32),
      'fc2_b':tf.get_variable(f"fc2_b_{n}", shape=[4], initializer=tf.zeros_initializer(), trainable=trainable, dtype=tf.float32)
      }
  return dictionary

online_weights={}
online_weights=dictionary_weights(online_weights, 'o', True)

target_weights={}
target_weights=dictionary_weights(target_weights, 't', False)

class NN():
  def __init__(self, X, weights):
    self.conv_layer1= conv_layer(X, weight_matrix=weights['conv1'], strides=4)
    self.conv_layer2= conv_layer(self.conv_layer1, weight_matrix=weights['conv2'], strides=2)
    self.conv_layer3= conv_layer(self.conv_layer2, weight_matrix=weights['conv3'], strides=1)
    self.flat= tf.reshape(self.conv_layer3, [-1,11*11*64])
    self.fc_1= fully_connected(self.flat, weights['fc1_w'], weights['fc1_b'], relu=True)
    self.logits= fully_connected(self.fc_1, weights['fc2_w'], weights['fc2_b'])

X = tf.placeholder(tf.float32, shape=(None, 84, 84, 4))
q_target = tf.placeholder(tf.float32, shape=(None))
action_taken = tf.placeholder(tf.int32, shape=(None, 2))

online_net=NN(X, online_weights)
target_net=NN(X, target_weights)

#Loss and Optimisation
q_pred=online_net.logits
q_pred_s_t_a_t=tf.gather_nd(q_pred,action_taken)
loss = tf.reduce_mean(tf.compat.v1.losses.mean_squared_error(predictions=q_pred_s_t_a_t, labels=q_target))
optimizer = tf.train.RMSPropOptimizer(learning_rate,decay) 
train_op = optimizer.minimize(loss)

#Copy Weights tf Group
op_list = []
for key in online_weights.keys():
  op_list+=[tf.assign(target_weights[key], online_weights[key])]
copy_weights=tf.group(op_list)

session=tf.Session()
session.run(tf.global_variables_initializer())

def sample_action(cur_state, epsn):
  if np.random.random_sample()<1-epsn:
    q_out=session.run([online_net.logits], {X: np.reshape(cur_state, [-1, 84, 84, 4])})
    a_t=np.argmax(q_out)
  else: 
    a_t=agent.actions[np.random.randint(0,len(agent.actions))]
  return a_t

i=0
s_t=env.reset()
s_t = np.array(s_t)
s_t = np.reshape(s_t, [-1] + list(s_t.shape))
train_eps_reward = 0.0
train_reward_list=[]
eval_reward_list=[]
loss_vec=[]
train_eps_count=0
while i<N:
  epsn=cal_epsilone(i)
  a_t=sample_action(s_t, epsn)
  s_t_1, r_t, omega_t, _ = env.step(a_t)
  s_t_1 = np.array(s_t_1)
  s_t_1 = np.reshape(s_t_1, [-1] + list(s_t_1.shape))

  i+=1
  train_eps_reward+=r_t
  agent.replay_buffer.append([s_t, a_t, s_t_1, r_t, int(omega_t)])  
  s_t = s_t_1
  if i > M:
    if(i % n == 0):
      B = np.array([agent.replay_buffer[i] for i in np.random.choice(10000,32,replace=False)])
      omega_vec = B[:,4]
      reward_vec = B[:,3]
      s_t_vec = np.vstack(B[:,0])
      s_t_1_vec = np.vstack(B[:,2])
      a_t_vec = B[:,1]
      a_t_vec= np.expand_dims(a_t_vec, axis=1)
      a_t_index = np.expand_dims(np.arange(32), axis=1)
      a_t_vec= np.concatenate((a_t_index, a_t_vec), axis=1)
      Q_t_1_max = session.run([target_net.logits], {X:s_t_1_vec})[0]
      Q_t_1_max = np.max(Q_t_1_max, axis=1)
      y = reward_vec + (1-omega_vec)*gamma*Q_t_1_max
      loss_val, _ = session.run([loss, train_op], {X:s_t_vec, q_target:y , action_taken: a_t_vec})
      loss_vec+=[loss_val]
      if(i%10000==0):
        print(f'Loss Value of iteration {i}: {loss_val}')

    if(i % C == 0):
      session.run([copy_weights])
    if(i % eval_freq == 0):
      avg_play_reward = 0.0
      for play in range(30):
        play_reward = 0.0
        for eps in range(5):
          eps_reward = 0.0
          omega_eps=False
          s_t_eval = env_eval.reset()
          s_t_eval = np.array(s_t_eval)
          while not omega_eps:
            a_t_eval=sample_action(s_t_eval, 0.001)
            s_t_1_eval, reward_, omega_eps, _ = env_eval.step(a_t_eval)
            s_t_1_eval = np.array(s_t_1_eval)
            eps_reward += reward_
            s_t_eval=s_t_1_eval
          play_reward += eps_reward
        avg_play_reward +=play_reward
      avg_play_reward /= 30.0
      eval_reward_list+=[avg_play_reward]
      print(f'Average reward for evaluation of iteration {i}: {avg_play_reward}')

  if(omega_t):
    train_eps_count+=1
    s_t=env.reset()
    s_t = np.array(s_t)
    s_t = np.reshape(s_t, [-1] + list(s_t.shape))
    train_reward_list+=[train_eps_reward]
    if(train_eps_count%200==0):
      print(f'Train Reward at episode end. Episode count {train_eps_count}: {train_eps_reward}')
    train_eps_reward=0