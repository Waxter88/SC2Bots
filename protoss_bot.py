from typing import Dict, Optional, Set, Union

from loguru import logger

from collections import deque

from sc2 import maps
from sc2.bot_ai import BotAI
from sc2.data import Difficulty, Race
from sc2.main import run_game
from sc2.player import Bot, Computer
from sc2.position import Point2
from sc2.unit import Unit
from sc2.units import Units
from sc2.ids.ability_id import AbilityId
from sc2.ids.buff_id import BuffId
from sc2.ids.unit_typeid import UnitTypeId
from sc2.ids.upgrade_id import UpgradeId

class WorkerStackBot(BotAI):
    def __init__(self):
        self.worker_to_mineral_patch_dict: Dict[int, int] = {}
        self.mineral_patch_to_list_of_workers: Dict[int, Set[int]] = {}
        self.minerals_sorted_by_distance: Units = Units([], self)
        self.townhall_distance_threshold = 0.15
        self.townhall_distance_factor = 1
        self.cybercore_started = False
        self.max_probes = 70
        self.supply_buffer = 4
        self.builders = set()

        self.build_order_queue = deque([
            UnitTypeId.GATEWAY,
            UnitTypeId.ASSIMILATOR,
            UnitTypeId.CYBERNETICSCORE,
            # Add more buildings as needed for your build order...
        ])

    async def on_start(self):
        self.client.game_step = 1
        await self.chat_send("(glhf)")
        await self.assign_initial_workers()
        
    async def on_step(self, iteration: int):
        await self.manage_worker_task()
        await self.produce_probes()
        await self.handle_idle_workers()
        await self.manage_supply()
        await self.manage_build_order()

    async def build_next_building(self):
        """Build the next building in the build order queue"""
        if self.build_order_queue:  # Fix for possible IndexError
            next_building = self.build_order_queue[0]
            building_place = await self.get_next_building_placement(next_building)
            logger.info(f"Building {next_building} at {building_place}")
            self.build(next_building, near=building_place)
        else:
            logger.info("Build order queue is empty")
            return

    async def manage_build_order(self):
        """Manage build order queue"""
        logger.info(f"Current build order queue: {self.build_order_queue}")

        if self.build_order_queue and self.already_pending(self.build_order_queue[0]):
            logger.info(f"Building {self.build_order_queue[0]} has been started. Removing from queue.")
            self.build_order_queue.popleft()

        if self.build_order_queue and self.can_afford(self.build_order_queue[0]):  
            if self.build_order_queue[0] == UnitTypeId.ASSIMILATOR:
                vgs = self.vespene_geyser.closer_than(10, self.townhalls.random)
                if vgs:
                    await self.build(self.build_order_queue[0], near=vgs.random)
            elif self.build_order_queue[0] == UnitTypeId.PYLON:
                await self.build(self.build_order_queue[0], near=self.townhalls.random.position.towards(self.game_info.map_center, 5))
            else:
                await self.build(self.build_order_queue[0], near=await self.find_placement(self.build_order_queue[0], self.townhalls.random.position.towards(self.game_info.map_center, 5)))



    async def build(self, building_type: UnitTypeId, near: Union[Point2, Unit] = None):
        if not near:
            # if pylon, build near nexuses
            if building_type == UnitTypeId.PYLON:
                # build near nexus in a valid location
                nexuses = self.townhalls.ready
                near = await self.find_placement(building_type, nexuses.random.position.towards(self.game_info.map_center, 5), placement_step=1)
           
            else:
                # get pylon that is ready
                pylons_ready = self.structures(UnitTypeId.PYLON).ready
                if not pylons_ready.exists:  # Check if we have any pylons that are ready
                    logger.warning("No pylon found")
                    return False
                pylon = pylons_ready.closest_to(self.townhalls.random)
                near = await self.find_placement(building_type, pylon, placement_step=10)
                logger.info(f"Next building placement for {building_type} is {near}")
        worker = self.select_build_worker(near)
        if worker:
            if self.can_afford(building_type):
                self.builders.add(worker.tag)
                worker.build(building_type, near) # TODO: check if building placement is valid
                logger.info(f"Building {building_type} near {near}")
                return True
            else:
                logger.warning(f"Can't afford to build {building_type}")
        else:
            logger.warning(f"No worker available to build {building_type} near {near}")
        return False


         
    async def get_next_building_placement(self, building_type: UnitTypeId):
        # For now we'll just place the building next to the main Nexus
        main_nexus = self.townhalls.ready.first
        if main_nexus:
            return await self.find_placement(building_type, main_nexus.position, placement_step=1)
        else:
            logger.error("No main Nexus found")
            return None

    async def manage_supply(self):
        if self.supply_left < self.supply_buffer and not self.already_pending(UnitTypeId.PYLON) and UnitTypeId.PYLON not in self.build_order_queue:
            # add pylon to build order queue
            self.build_order_queue.appendleft(UnitTypeId.PYLON)
            logger.info(f"Added {UnitTypeId.PYLON} to build order queue")
        elif self.supply_left > 2 * self.supply_buffer:
            # remove pylon from build order queue
            if UnitTypeId.PYLON in self.build_order_queue:
                self.build_order_queue.remove(UnitTypeId.PYLON)
                logger.info(f"Removed {UnitTypeId.PYLON} from build order queue")
            
                    
    async def handle_idle_workers(self):
       for worker in self.workers.idle:
            if worker.tag in self.builders:
                continue  # Don't interfere with builders
            if not worker.orders:
                self.builders.discard(worker.tag)

            await self.assign_worker_to_mineral_patch(worker)
            mineral_tag = self.worker_to_mineral_patch_dict.get(worker.tag, None)
            if mineral_tag:
                minerals_with_given_tag = self.mineral_field.filter(lambda m: m.tag == mineral_tag)
                if minerals_with_given_tag:
                    mineral = minerals_with_given_tag.first
                    worker.gather(mineral)
                else:
                    logger.warning(f"No mineral patch found with tag {mineral_tag}. Reassigning worker.")
                    await self.assign_worker_to_mineral_patch(worker)

    async def produce_probes(self):
        # Check if the total number of probes is less than max_probes
        if self.workers.amount < self.max_probes:
            for nexus in self.townhalls.idle:  # Only idle Nexuses, to prevent overriding other commands
                # Ensure we have enough resources and the Nexus isn't already training a probe
                if self.can_afford(UnitTypeId.PROBE):
                    nexus.train(UnitTypeId.PROBE)

    async def assign_initial_workers(self):
        for nexus in self.townhalls:  # loop through all nexuses
            minerals_near_nexus = self.mineral_field.closer_than(10, nexus.position).sorted_by_distance_to(nexus.position)
            for mineral in minerals_near_nexus:
                workers = self.workers.tags_not_in(self.worker_to_mineral_patch_dict).sorted_by_distance_to(mineral)
                for worker in workers:
                    # set worker.is_builder to False to allow it to be assigned to mine
                    worker.is_builder = False
                    if len(self.mineral_patch_to_list_of_workers.get(mineral.tag, [])) < 2:
                        self.mineral_patch_to_list_of_workers.setdefault(mineral.tag, set()).add(worker.tag)
                        self.worker_to_mineral_patch_dict[worker.tag] = mineral.tag

    async def assign_worker_to_mineral_patch(self, worker: Unit):
        # Populate the list of minerals sorted by distance if it's empty
        if not self.minerals_sorted_by_distance:
            print("Sorting minerals by distance")
            self.minerals_sorted_by_distance = self.mineral_field.sorted_by_distance_to(self.townhalls.closest_to(worker))
        
        closest_nexus = self.townhalls.closest_to(worker)
        minerals_near_nexus = self.mineral_field.closer_than(10, closest_nexus.position).sorted_by_distance_to(worker.position)
        
        # Try to assign optimally first
        for mineral in minerals_near_nexus:
            if len(self.mineral_patch_to_list_of_workers.get(mineral.tag, set())) < 2:
                self.mineral_patch_to_list_of_workers.setdefault(mineral.tag, set()).add(worker.tag)
                self.worker_to_mineral_patch_dict[worker.tag] = mineral.tag
                return
                
        # If everything is saturated, assign to the closest mineral for sub-optimal mining
        closest_mineral = self.minerals_sorted_by_distance[0]
        self.mineral_patch_to_list_of_workers.setdefault(closest_mineral.tag, set()).add(worker.tag)
        self.worker_to_mineral_patch_dict[worker.tag] = closest_mineral.tag

    async def manage_worker_task(self):
        # Handle worker to mineral/gas assignments
        minerals: Dict[int, Unit] = {mineral.tag: mineral for mineral in self.mineral_field}
        for worker in self.workers:
            if worker.tag in self.builders:
                continue  # Don't interfere with builders

            if not self.townhalls:
                logger.error("All townhalls died - can't return resources")
                break
            if worker.tag in self.worker_to_mineral_patch_dict:
                mineral_tag = self.worker_to_mineral_patch_dict[worker.tag]
                mineral = minerals.get(mineral_tag, None)
            else:
                await self.assign_worker_to_mineral_patch(worker)
                mineral_tag = self.worker_to_mineral_patch_dict.get(worker.tag, None)
                mineral = minerals.get(mineral_tag, None)

            if not worker.is_carrying_minerals:
                if not worker.is_gathering or worker.order_target != mineral.tag:
                    worker.gather(mineral)
            else:
                if mineral:
                    if not worker.is_gathering or worker.order_target != mineral.tag:
                        worker.gather(mineral)
                th = self.townhalls.closest_to(worker)
                # Calculate the point just in front of the Nexus
                pos: Point2 = th.position.towards(worker.position, th.radius + self.townhall_distance_threshold)

                # If the worker is further away from that point, move it to that point
                if worker.distance_to(pos) > self.townhall_distance_threshold:
                    worker.move(pos)
                else:
                    # If the worker is close to that point, order it to return resources
                    worker.return_resource()
                    # After returning, make the worker gather minerals again (if available)
                    if mineral:
                        worker.gather(mineral, queue=True)

    

    # ... [ Other functions including handle_expansions, manage_buildings, etc. ]

    

def main():
    run_game(
        maps.get("AbyssalReefLE"),
        [Bot(Race.Protoss, WorkerStackBot()),
         Computer(Race.Terran, Difficulty.Medium)],
        realtime=False,
        random_seed=0,
    )

if __name__ == "__main__":
    main()
