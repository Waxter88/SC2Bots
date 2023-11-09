from pysc2.agents import base_agent
from pysc2.env import sc2_env
from pysc2.lib import actions, features, units
from absl import app

import random

class ZergAgent(base_agent.BaseAgent):
  def unit_type_is_selected(self, obs, unit_type):
    if ((len(obs.observation.single_select) > 0 ) and 
      obs.observation.single_select[0].unit_type == unit_type):
      return True 
    if (len(obs.observation.multi_select) > 0 and 
      obs.observation.multi_select[0].unit_type == unit_type):
      return True 
    return False

  def get_units_by_type(self, obs, unit_type):  
      return [unit for unit in obs.observation.feature_units
              if unit.unit_type == unit_type]

  def can_do(self, obs, action):
    return action in obs.observation.available_actions            

  def step(self, obs):
    super(ZergAgent, self).step(obs)

  def build_spawning_pool(self, obs):
    spawning_pool = self.get_units_by_type(obs, units.Zerg.SpawningPool)
    #if there is no spawning pool, build one
    if len (spawning_pool) == 0:
    #if drone is selected build spawning pool
      if self.unit_type_is_selected(obs, units.Zerg.Drone):
            if self.can_do(obs, actions.FUNCTIONS.Build_SpawningPool_screen.id):
                x = random.randint(1, 63)
                y = random.randint(1, 63)

                return actions.FUNCTIONS.Build_SpawningPool_screen('now', (x, y))


      drones = self.get_units_by_type(obs, units.Zerg.Drone)         
      if len(drones) > 0 :
        drone_unit = random.choice(drones)
        if drone.x >= 0 and drone.y >= 0:
          return actions.FUNCTIONS.select_point('select_all_type',(drones.x, drones.y))

  if self.unit_type_is_selected(obs, units.Zerg.Larva):  
      if self.can_do(obs, actions.FUNCTIONS.Train_Drone_quick.id):
        return actions.FUNCTIONS.Train_Drone_quick('now')

  larva_units = self.get_units_by_type(units.Zerg.Larva)

  if len(larva_units) > 0:
      larva_unit = random.choice(larva_units)
      return actions.FUNCTIONS.select_point('select_all_type',(larva_unit.x, larva_unit.y))


    return actions.FUNCTIONS.no_op()

def main(unused_argv):
  map = "AbyssalReef"
  agent = ZergAgent()
  try:
    while True:
      with sc2_env.SC2Env(
          map_name=map,
          players=[sc2_env.Agent(sc2_env.Race.zerg),
                   sc2_env.Bot(sc2_env.Race.random,
                               sc2_env.Difficulty.very_easy)],
          agent_interface_format=features.AgentInterfaceFormat(
              feature_dimensions=features.Dimensions(screen=84, minimap=64),
              use_feature_units=True),
          step_mul=16,
          game_steps_per_episode=0,
          visualize=True) as env:
          
        agent.setup(env.observation_spec(), env.action_spec())
        
        timesteps = env.reset()
        agent.reset()
        
        while True:
          step_actions = [agent.step(timesteps[0])]
          if timesteps[0].last():
            break
          timesteps = env.step(step_actions)
      
  except KeyboardInterrupt:
    pass
  
if __name__ == "__main__":
  app.run(main)