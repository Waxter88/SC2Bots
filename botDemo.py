from pysc2.agents import base_agent
from pysc2.env import sc2_env
from pysc2.lib import actions, features, units
from absl import app
import random

ban = 0
hatch = True
harvest = False

#obs is the object that contains all the observactions we need it

class ZergAgent(base_agent.BaseAgent):

  def __init__(self):
    """initialize a variable"""
    super(ZergAgent, self).__init__()
    
    self.attack_coordinates = None
    self.safe_coordinates = None
    self.expand = None



  def unit_type_is_selected(self, obs, unit_type):

    """utility fuction to simply sintax of unit type
    selected check"""
    if (len(obs.observation.single_select) > 0 and
            obs.observation.single_select[0].unit_type == unit_type):
        return True

    if (len(obs.observation.multi_select) > 0 and
            obs.observation.multi_select[0].unit_type == unit_type):
        return True

    return False

  def get_units_by_type(self, obs, unit_type):

    """utility fuction to simply sintax of unit
    selection by type"""
    return [unit for unit in obs.observation.feature_units
            if unit.unit_type == unit_type]

  def can_do(self, obs, action):

    """utility fuction to simply sintax of
    available actions check"""
    return action in obs.observation.available_actions

  # def my_attack(self, obs):
  #   #if enough zerglings,send attack
  #   zerglings = self.get_units_by_type(obs, units.Zerg.Zergling)
  #   if len(zerglings) >= 20:
  #       #send attack at attack locations
  #       if self.unit_type_is_selected(obs, units.Zerg.Zergling):
  #           if self.can_do(obs, actions.FUNCTIONS.Attack_minimap.id):
  #               return actions.FUNCTIONS.Attack_minimap("now", self.attack_coordinates)
  #
  #       #select zerglings
  #       if self.can_do(obs, actions.FUNCTIONS.select_army.id):
  #           return actions.FUNCTIONS.select_army("select")

  def my_attack(self, obs):
    #if enough zerglings,send attack
    zerglings = self.get_units_by_type(obs, units.Zerg.Zergling)
    mutalisk = self.get_units_by_type(obs, units.Zerg.Mutalisk)
    corruptor = self.get_units_by_type(obs, units.Zerg.Corruptor)
    hydras = self.get_units_by_type(obs, units.Zerg.Hydralisk)
    lurker = self.get_units_by_type(obs, units.Zerg.Lurker)
    if len(zerglings) >= 5 and len(lurker) >= 1 :
        #send attack at attack locations
        if self.unit_type_is_selected(obs, units.Zerg.Zergling) or self.unit_type_is_selected(obs, units.Zerg.Mutalisk) or self.unit_type_is_selected(obs, units.Zerg.Corruptor) or self.unit_type_is_selected(obs, units.Zerg.Hydralisk) or self.unit_type_is_selected(obs, units.Zerg.Lurker):
            if self.can_do(obs, actions.FUNCTIONS.Attack_minimap.id):
                return actions.FUNCTIONS.Attack_minimap("now",self.attack_coordinates)

        #select zerglings
        if self.can_do(obs, actions.FUNCTIONS.select_army.id):
            return actions.FUNCTIONS.select_army("select")

  def my_spawning_pool(self, obs):
    #if there is no barraks (spawning pool) build one
    spawning_pools = self.get_units_by_type(obs, units.Zerg.SpawningPool)
    if len (spawning_pools) == 0 :
        # if drone is selected build spawning pool
        if self.unit_type_is_selected(obs, units.Zerg.Drone):
            if self.can_do(obs,actions.FUNCTIONS.Build_SpawningPool_screen.id):
                x = random.randint(0,63)
                y = random.randint(0,63)

                return actions.FUNCTIONS.Build_SpawningPool_screen("now", (x,y))

        # select some random drone for the next choice
        drones = self.get_units_by_type(obs, units.Zerg.Drone)
        if len(drones) > 0 :
            drone = random.choice(drones)
            if drone.x >= 0 and drone.y >= 0:
                return actions.FUNCTIONS.select_point("select_all_type",(drone.x, drone.y))

  def my_extractor(self, obs):
    #if there is no barraks (spawning pool) build one
    extractor = self.get_units_by_type(obs, units.Zerg.Extractor)
    if len (extractor) < 2 :
        # if drone is selected build spawning pool
        if self.unit_type_is_selected(obs, units.Zerg.Drone):
            if self.can_do(obs,actions.FUNCTIONS.Build_Extractor_screen.id):
                geysers = self.get_units_by_type(obs, units.Neutral.VespeneGeyser)
                if len(geysers) > 0 :
                    geyser = random.choice(geysers)
                    #VespeneGeyser
                    return actions.FUNCTIONS.Build_Extractor_screen("now", (geyser.x,geyser.y))

        # select some random drone for the next choice
        drones = self.get_units_by_type(obs, units.Zerg.Drone)
        if len(drones) > 0 :
            drone = random.choice(drones)
            if drone.x >= 0 and drone.y >= 0:
                return actions.FUNCTIONS.select_point("select_all_type",(drone.x,drone.y))

  def my_harvest_gas(self,obs):
        extractor = self.get_units_by_type(obs, units.Zerg.Extractor)
        if len(extractor) > 0:
            extractor = random.choice(extractor)
            if extractor['assigned_harvesters'] < 3:
                global harvest
                if self.unit_type_is_selected(obs, units.Zerg.Drone) and harvest:
                    if len(obs.observation.single_select) < 2 and len(obs.observation.multi_select) < 2 :
                        if self.can_do(obs,actions.FUNCTIONS.Harvest_Gather_screen.id):
                            harvest = False
                            return actions.FUNCTIONS.Harvest_Gather_screen("now",(extractor.x, extractor.y))


                drones = self.get_units_by_type(obs, units.Zerg.Drone)
                if len(drones) > 0 :
                    drone = random.choice(drones)
                    if drone.x >= 0 and drone.y >= 0:
                        harvest = True
                        return actions.FUNCTIONS.select_point("select",(drone.x,drone.y))

  def my_more_units(self, obs, type):
    #make units
    if self.unit_type_is_selected(obs, units.Zerg.Larva):
        free_supply = (obs.observation.player.food_cap - obs.observation.player.food_used)

        # if there are no more houses (overlords) build more
        if free_supply < 6 :
            if self.can_do(obs, actions.FUNCTIONS.Train_Overlord_quick.id):
                return actions.FUNCTIONS.Train_Overlord_quick("now")

        if type == "zergling":
            # if it is possible build troops
            if self.can_do(obs, actions.FUNCTIONS.Train_Zergling_quick.id):
                    return actions.FUNCTIONS.Train_Zergling_quick("now")

        if type == "drone":
            if self.can_do(obs, actions.FUNCTIONS.Train_Drone_quick.id):
                    return actions.FUNCTIONS.Train_Drone_quick("now")

        if type == "mutalisk":
            if self.can_do(obs, actions.FUNCTIONS.Train_Mutalisk_quick.id):
                    return actions.FUNCTIONS.Train_Mutalisk_quick("now")

        if type == "corruptor":
            if self.can_do(obs, actions.FUNCTIONS.Train_Corruptor_quick.id):
                    return actions.FUNCTIONS.Train_Corruptor_quick("now")

        if type == "hydralisk":
            if self.can_do(obs, actions.FUNCTIONS.Train_Hydralisk_quick.id):
                    return actions.FUNCTIONS.Train_Hydralisk_quick("now")

    larvae = self.get_units_by_type(obs, units.Zerg.Larva)
    if len(larvae) > 0 :
        larva = random.choice(larvae)
        if larva.x >= 0 and larva.y >= 0:
            return actions.FUNCTIONS.select_point("select_all_type", (larva.x, larva.y))

  def my_lurker(self, obs):
    #make units
    if self.unit_type_is_selected(obs, units.Zerg.Hydralisk):
        if self.can_do(obs, actions.FUNCTIONS.Morph_Lurker_quick.id):
                return actions.FUNCTIONS.Morph_Lurker_quick("now")

    hyd = self.get_units_by_type(obs, units.Zerg.Hydralisk)
    if len(hyd) > 0 :
        hyd = random.choice(hyd)
        if hyd.x >= 0 and hyd.y >= 0:
            return actions.FUNCTIONS.select_point("select_all_type", (hyd.x, hyd.y))

  def my_build_hatchery(self, obs):
    #if there is no barraks (spawning pool) build one
    global hatch
    if hatch:
        # if drone is selected build spawning pool
        if self.unit_type_is_selected(obs, units.Zerg.Drone):
            if self.can_do(obs,actions.FUNCTIONS.Build_Hatchery_screen.id):
                global ban
                if ban == 0:
                    ban = 1
                    return actions.FUNCTIONS.move_camera(self.expand)
                ban = 2
                hatch = False
                x = random.randint(0,63)
                y = random.randint(0,63)

                return actions.FUNCTIONS.Build_Hatchery_screen("now", (32,32))

        # select some random drone for the next choice
        drones = self.get_units_by_type(obs, units.Zerg.Drone)
        if len(drones) > 0 :
            drone = random.choice(drones)
            if drone.x >= 0 and drone.y >= 0:
                return actions.FUNCTIONS.select_point("select_all_type",(drone.x, drone.y))

  def my_harvest_mineral(self,obs):
      hatchery = self.get_units_by_type(obs, units.Zerg.Hatchery)
      lair = self.get_units_by_type(obs, units.Zerg.Lair)
      if len(hatchery) > 0 or len(lair) > 0:
          bool = False
          if len(hatchery) > 0:
              hatchery = random.choice(hatchery)
              if hatchery['assigned_harvesters'] < 7:
                bool = True
          elif len(lair) > 0:
              lair = random.choice(lair)
              if lair['assigned_harvesters'] < 7:
                bool = True
          if bool:
                global harvest
                if self.unit_type_is_selected(obs, units.Zerg.Drone) and harvest:
                    if len(obs.observation.single_select) < 2 and len(obs.observation.multi_select) < 2 :
                        if self.can_do(obs,actions.FUNCTIONS.Harvest_Gather_screen.id):
                            minerals = self.get_units_by_type(obs, units.Neutral.MineralField)
                            if len(minerals) > 0 :
                                #mineral
                                mineral = random.choice(minerals)
                                harvest = False
                                return actions.FUNCTIONS.Harvest_Gather_screen("now", (mineral.x,mineral.y))

                # select some random drone for the next choice
                drones = self.get_units_by_type(obs, units.Zerg.Drone)
                if len(drones) > 0 :
                    drone = random.choice(drones)
                    if drone.x >= 0 and drone.y >= 0:
                        harvest = True
                        return actions.FUNCTIONS.select_point("select",(drone.x,drone.y))

  def my_den(self, obs):
    den = self.get_units_by_type(obs, units.Zerg.HydraliskDen)
    if len(den) == 0 :
        if self.unit_type_is_selected(obs, units.Zerg.Drone):
            if self.can_do(obs,actions.FUNCTIONS.Build_HydraliskDen_screen.id):
                x = random.randint(0,63)
                y = random.randint(0,63)

                return actions.FUNCTIONS.Build_HydraliskDen_screen("now", (x,y))

        # select some random drone for the next choice
        drones = self.get_units_by_type(obs, units.Zerg.Drone)
        if len(drones) > 0 :
            drone = random.choice(drones)
            if drone.x >= 0 and drone.y >= 0:
                return actions.FUNCTIONS.select_point("select_all_type",(drone.x, drone.y))

  def my_spire(self, obs):
    spire = self.get_units_by_type(obs, units.Zerg.Spire)
    if len(spire) == 0 :
        if self.unit_type_is_selected(obs, units.Zerg.Drone):
            if self.can_do(obs,actions.FUNCTIONS.Build_Spire_screen.id):
                x = random.randint(0,63)
                y = random.randint(0,63)

                return actions.FUNCTIONS.Build_Spire_screen("now", (x,y))

        # select some random drone for the next choice
        drones = self.get_units_by_type(obs, units.Zerg.Drone)
        if len(drones) > 0 :
            drone = random.choice(drones)
            if drone.x >= 0 and drone.y >= 0:
                return actions.FUNCTIONS.select_point("select_all_type",(drone.x, drone.y))

  def my_lurkerd(self, obs):
    lurkerd = self.get_units_by_type(obs, units.Zerg.LurkerDen)
    if len(lurkerd) == 0 :
        if self.unit_type_is_selected(obs, units.Zerg.Drone):
            if self.can_do(obs,actions.FUNCTIONS.Build_LurkerDen_screen.id):
                x = random.randint(0,63)
                y = random.randint(0,63)

                return actions.FUNCTIONS.Build_LurkerDen_screen("now", (x,y))

        # select some random drone for the next choice
        drones = self.get_units_by_type(obs, units.Zerg.Drone)
        if len(drones) > 0 :
            drone = random.choice(drones)
            if drone.x >= 0 and drone.y >= 0:
                return actions.FUNCTIONS.select_point("select_all_type",(drone.x, drone.y))

  def my_lairs(self, obs):
    #if there is no barraks (spawning pool) build one
    lairs = self.get_units_by_type(obs, units.Zerg.Lair)
    if len(lairs) == 0 :
        # if drone is selected build spawning pool
        if self.unit_type_is_selected(obs, units.Zerg.Hatchery):
            if self.can_do(obs,actions.FUNCTIONS.Morph_Lair_quick.id):
                return actions.FUNCTIONS.Morph_Lair_quick("now")

        # select some random drone for the next choice
        hatchery = self.get_units_by_type(obs, units.Zerg.Hatchery)
        if len(hatchery) > 0 :
            hatchery = random.choice(hatchery)
            if hatchery.x >= 0 and hatchery.y >= 0:
                return actions.FUNCTIONS.select_point("select_all_type",(hatchery.x, hatchery.y))

  def step(self, obs):
    super(ZergAgent, self).step(obs)


    #select/guess the location of the enemies
    if obs.first():
        player_y, player_x = (obs.observation.feature_minimap.player_relative == features.PlayerRelative.SELF).nonzero()

        xmean = player_x.mean()
        ymean = player_y.mean()

        if xmean <= 31 and ymean <= 31:
            #set pair of coordintates
            self.attack_coordinates = [40,47]
            self.safe_coordinates = [20,25]
            self.expand = [49,22]
        else:
            #set pair of coordintates
            self.attack_coordinates = [20,25]
            self.safe_coordinates = [40,47]
            self.expand = [19,49]

    global ban
    if ban == 2:
        ban = 0
        return actions.FUNCTIONS.move_camera(self.safe_coordinates)

    #python always includes by default "self" as a parameter in the call
    attack = self.my_attack(obs)
    if attack:
        return attack

    minerals = self.get_units_by_type(obs, units.Neutral.MineralField)
    if len(minerals) < 4 and ban == 0:
        #make more zerglings
        zerglings =  self.get_units_by_type(obs, units.Zerg.Zergling)
        if len(zerglings) <= 5:
            make_units = self.my_more_units(obs,"zergling")
            if make_units:
                return make_units
        #make more mutalisk
        spire =  self.get_units_by_type(obs, units.Zerg.Spire)
        if len(spire) > 0:
            mutalisk =  self.get_units_by_type(obs, units.Zerg.Mutalisk)
            if len(mutalisk) <= 1:
                make_units = self.my_more_units(obs,"mutalisk")
                if make_units:
                    return make_units

        #make more corruptor
        spire =  self.get_units_by_type(obs, units.Zerg.Spire)
        if len(spire) > 0:
            corruptor =  self.get_units_by_type(obs, units.Zerg.Corruptor)
            if len(corruptor) <= 1:
                make_units = self.my_more_units(obs,"corruptor")
                if make_units:
                    return make_units

        #make more hydras
        lair =  self.get_units_by_type(obs, units.Zerg.Lair)
        if len(lair) > 0:
            hydras =  self.get_units_by_type(obs, units.Zerg.Hydralisk)
            if len(hydras) <= 1:
                make_units = self.my_more_units(obs,"hydralisk")
                if make_units:
                    return make_units

        #make more lurker
        hyd =  self.get_units_by_type(obs, units.Zerg.Hydralisk)
        if len(hyd) > 0:
            lurker =  self.get_units_by_type(obs, units.Zerg.Lurker)
            if len(lurker) <= 1:
                make_units = self.my_lurker(obs)
                if make_units:
                    return make_units

        ban = 1

        return actions.FUNCTIONS.move_camera(self.expand)

    hatchery = self.get_units_by_type(obs, units.Zerg.Hatchery)
    lair = self.get_units_by_type(obs, units.Zerg.Lair)

    #build spawning pool
    if len(hatchery) == 1 or len(lair) == 1:
        spawning_pool = self.my_spawning_pool(obs)
        if spawning_pool:
            return spawning_pool

    #build hatchery
    hatchery = self.my_build_hatchery(obs)
    if hatchery:
        return hatchery

    #mine minerals
    if ban == 1:
        drones =  self.get_units_by_type(obs, units.Zerg.Drone)
        if len(drones) > 6:
            mine = self.my_harvest_mineral(obs)
            if mine:
                return mine

    #make more drones
    drones =  self.get_units_by_type(obs, units.Zerg.Drone)
    size = len(drones)
    # if ban == 1:
    #     size = size * 2 - 1
    if size <= 11:
        make_units = self.my_more_units(obs,"drone")
        if make_units:
            return make_units

    #make more zerglings
    zerglings =  self.get_units_by_type(obs, units.Zerg.Zergling)
    if len(zerglings) <= 5:
        make_units = self.my_more_units(obs,"zergling")
        if make_units:
            return make_units

    global hatch
    hatchery = self.get_units_by_type(obs, units.Zerg.Hatchery)
    lair = self.get_units_by_type(obs, units.Zerg.Lair)

    #build extractor
    if len(hatchery) == 1 or len(lair) == 1:
        if ban == 0:
            extractor = self.my_extractor(obs)
            if extractor:
                return extractor
        elif ban == 1 and not hatch:
            extractor = self.my_extractor(obs)
            if extractor:
                return extractor

    #harvest gas
    lurks =  self.get_units_by_type(obs, units.Zerg.LurkerDen)
    if len(lurks) < 1:
        if len(hatchery) == 1 or len(lair) == 1:
            gas = self.my_harvest_gas(obs)
            if gas:
                return gas

    #build Lair
    if len(hatchery) == 1 or len(lair) == 1:
        lairs = self.my_lairs(obs)
        if lairs:
            return lairs

    #build Spire
    if len(hatchery) == 1 or len(lair) == 1:
        if ban == 0:
            spire = self.my_spire(obs)
            if spire:
                return spire
        elif ban == 1 and not hatch:
            spire = self.my_spire(obs)
            if spire:
                return spire

    #build Den
    if len(hatchery) == 1 or len(lair) == 1:
        if ban == 0:
            den = self.my_den(obs)
            if den:
                return den
        elif ban == 1 and not hatch:
            den = self.my_den(obs)
            if den:
                return den

    #build lurker den
    if len(hatchery) == 1 or len(lair) == 1:
        if ban == 0:
            lurkerd = self.my_lurkerd(obs)
            if lurkerd:
                return lurkerd
        elif ban == 1 and not hatch:
            lurkerd = self.my_lurkerd(obs)
            if lurkerd:
                return lurkerd

    #make more mutalisk
    spire =  self.get_units_by_type(obs, units.Zerg.Spire)
    if len(spire) > 0:
        mutalisk =  self.get_units_by_type(obs, units.Zerg.Mutalisk)
        if len(mutalisk) <= 1:
            make_units = self.my_more_units(obs,"mutalisk")
            if make_units:
                return make_units

    #make more corruptor
    spire =  self.get_units_by_type(obs, units.Zerg.Spire)
    if len(spire) > 0:
        corruptor =  self.get_units_by_type(obs, units.Zerg.Corruptor)
        if len(corruptor) <= 1:
            make_units = self.my_more_units(obs,"corruptor")
            if make_units:
                return make_units

    #make more hydras
    lair =  self.get_units_by_type(obs, units.Zerg.Lair)
    if len(lair) > 0:
        hydras =  self.get_units_by_type(obs, units.Zerg.Hydralisk)
        if len(hydras) <= 1:
            make_units = self.my_more_units(obs,"hydralisk")
            if make_units:
                return make_units

    #make more lurker
    hyd =  self.get_units_by_type(obs, units.Zerg.Hydralisk)
    if len(hyd) > 0:
        lurker =  self.get_units_by_type(obs, units.Zerg.Lurker)
        if len(lurker) <= 1:
            make_units = self.my_lurker(obs)
            if make_units:
                return make_units

    if ban == 0:
        ban = 1
        return actions.FUNCTIONS.move_camera(self.expand)
    elif ban == 1:
        hatchery = self.get_units_by_type(obs, units.Zerg.Hatchery)
        if len(hatchery) < 1:
            hatch = True
        ban = 2

    return actions.FUNCTIONS.no_op()  #do not do anything if there were no matches

def main(unused_argv):
  agent = ZergAgent()
  try:
    while True:
      with sc2_env.SC2Env(
        map_name="AbyssalReef",
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