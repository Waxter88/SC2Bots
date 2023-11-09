"""
This bot attempts to stack workers 'perfectly'.
This is only a demo that works on game start, but does not work when adding more workers or bases.

This bot exists only to showcase how to keep track of mineral tag over multiple steps / frames.

Task for the user who wants to enhance this bot:
- Allow mining from vespene geysirs
- Remove dead workers and re-assign (new) workers to that mineral patch, or pick a worker from a long distance mineral patch
- Re-assign workers when new base is completed (or near complete)
- Re-assign workers when base died
- Re-assign workers when mineral patch mines out
- Re-assign workers when gas mines out
"""

from typing import Dict, Set

from loguru import logger

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


# pylint: disable=W0231
class WorkerStackBot(BotAI):

    def __init__(self):
        self.worker_to_mineral_patch_dict: Dict[int, int] = {}
        self.mineral_patch_to_list_of_workers: Dict[int, Set[int]] = {}
        self.minerals_sorted_by_distance: Units = Units([], self)
        # Distance 0.01 to 0.1 seems fine
        self.townhall_distance_threshold = 0.01
        # Distance factor between 0.95 and 1.0 seems fine
        self.townhall_distance_factor = 1
        self.cybercore_started = False

    async def on_start(self):
        self.client.game_step = 1
        await self.assign_workers()

    async def assign_workers(self):
        self.minerals_sorted_by_distance = self.mineral_field.closer_than(10,
                                                                          self.start_location).sorted_by_distance_to(
                                                                              self.start_location
                                                                          )

        # Assign workers to mineral patch, start with the mineral patch closest to base
        for mineral in self.minerals_sorted_by_distance:
            # Assign workers closest to the mineral patch
            workers = self.workers.tags_not_in(self.worker_to_mineral_patch_dict).sorted_by_distance_to(mineral)
            for worker in workers:
                # Assign at most 2 workers per patch
                # This dict is not really used further down the code, but useful to keep track of how many workers are assigned to this mineral patch - important for when the mineral patch mines out or a worker dies
                if len(self.mineral_patch_to_list_of_workers.get(mineral.tag, [])) < 2:
                    if len(self.mineral_patch_to_list_of_workers.get(mineral.tag, [])) == 0:
                        self.mineral_patch_to_list_of_workers[mineral.tag] = {worker.tag}
                    else:
                        self.mineral_patch_to_list_of_workers[mineral.tag].add(worker.tag)
                    # Keep track of which mineral patch the worker is assigned to - if the mineral patch mines out, reassign the worker to another patch
                    self.worker_to_mineral_patch_dict[worker.tag] = mineral.tag
                else:
                    break

    async def assign_worker_to_mineral_patch(self, worker: Unit):
        # Try to find a mineral patch that has less than 2 workers
        for mineral in self.minerals_sorted_by_distance:
            if len(self.mineral_patch_to_list_of_workers.get(mineral.tag, set())) < 2:
                self.mineral_patch_to_list_of_workers.setdefault(mineral.tag, set()).add(worker.tag)
                self.worker_to_mineral_patch_dict[worker.tag] = mineral.tag
                break
        else:
            # If all patches have 2 workers, just assign to the closest mineral patch
            closest_mineral = self.minerals_sorted_by_distance[0]
            self.mineral_patch_to_list_of_workers.setdefault(closest_mineral.tag, set()).add(worker.tag)
            self.worker_to_mineral_patch_dict[worker.tag] = closest_mineral.tag
            logger.warning(f"Could not find a mineral patch with less than 2 workers, assigning worker {worker.tag} to the closest mineral patch {closest_mineral.tag}")

    async def custom_distribute_workers(self):
        # Check for idle workers, and re-assign them to the closest mineral patch
        idle_workers = self.workers.filter(lambda w: w.is_idle)
        for worker in idle_workers:
            await self.assign_worker_to_mineral_patch(worker)
        # Stop mining gas if collected more than 150
        if self.vespene > 150:
            for gas_worker in self.workers.filter(lambda w: w.is_carrying_vespene):
                await self.assign_worker_to_mineral_patch(gas_worker)
        else:
            # Assign workers to gas
            for gas in self.structures(UnitTypeId.ASSIMILATOR).ready:
                if gas.assigned_harvesters < gas.ideal_harvesters:
                    worker = self.select_build_worker(gas.position)
                    if worker:
                        worker.gather(gas)

        # Get all mineral patches that have less than 2 workers
        under_assigned_minerals = [mineral for mineral, workers in self.mineral_patch_to_list_of_workers.items() if len(workers) < 2]
        
        # Redistribute workers from saturated bases to unsaturated ones
        for th in self.townhalls.ready:
            # print number of townhalls, number of workers assigned to it, and number of workers that should be assigned to it
            logger.info(f"Townhall {th.tag} has {len(self.mineral_patch_to_list_of_workers.get(th.tag, []))} workers assigned, and should have {th.ideal_harvesters} workers assigned")
            if th.assigned_harvesters > 16:
                excess = th.assigned_harvesters - 16
                for _ in range(excess):
                    worker = self.workers.closest_to(th.position)
                    if under_assigned_minerals:
                        target_mineral = under_assigned_minerals.pop()
                        self.mineral_patch_to_list_of_workers[target_mineral].add(worker.tag)
                        self.worker_to_mineral_patch_dict[worker.tag] = target_mineral
                        worker.gather(self.mineral_field.find_by_tag(target_mineral))
                    else:
                        # All patches seem saturated, just assign to any patch
                        await self.assign_worker_to_mineral_patch(worker)


    async def on_step(self, iteration: int):
        nexus = self.townhalls.ready.random

        # Check if the number of mineral patches we are tracking is different from actual mineral patches in the game
        if len(self.minerals_sorted_by_distance) != self.mineral_field.amount:
            await self.assign_workers()

        # If this random nexus is not idle and has not chrono buff, chrono it with one of the nexuses we have
        if not nexus.is_idle and not nexus.has_buff(BuffId.CHRONOBOOSTENERGYCOST):
            nexuses = self.structures(UnitTypeId.NEXUS)
            abilities = await self.get_available_abilities(nexuses)
            for loop_nexus, abilities_nexus in zip(nexuses, abilities):
                if AbilityId.EFFECT_CHRONOBOOSTENERGYCOST in abilities_nexus:
                    loop_nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, nexus)
                    break

        unassigned_workers = self.workers.tags_not_in(self.worker_to_mineral_patch_dict)
        for worker in unassigned_workers:
            await self.assign_worker_to_mineral_patch(worker)

        # If we have less than 5 nexuses and none pending yet, expand
        if self.townhalls.ready.amount + self.already_pending(UnitTypeId.NEXUS) < 5:
            if self.can_afford(UnitTypeId.NEXUS):
                await self.expand_now()

        # Distribute workers in gas and across bases
        await self.distribute_workers()
        #await self.custom_distribute_workers()
        

        # Build pylon when on low supply
        if self.supply_left < 4 and self.already_pending(UnitTypeId.PYLON) == 0:
            # Always check if you can afford something before you build it
            if self.can_afford(UnitTypeId.PYLON):
                # make sure the pylon is not inside the mineral line
                await self.build(UnitTypeId.PYLON, near=nexus.position.towards(self.game_info.map_center, 5))
                #await self.build(UnitTypeId.PYLON, near=nexus)
            return

        # If we have less than 22 workers, and a nexus is ready, train a worker
        if self.supply_workers + self.already_pending(UnitTypeId.PROBE) < self.townhalls.amount * 22 and nexus.is_idle:
            if self.can_afford(UnitTypeId.PROBE):
                nexus.train(UnitTypeId.PROBE)

        # Once we have a pylon
        if self.structures(UnitTypeId.PYLON).ready:
            pylon = self.structures(UnitTypeId.PYLON).ready.random
            # If we have no gateways, build one
            if not self.structures(UnitTypeId.GATEWAY):
                if self.can_afford(UnitTypeId.GATEWAY):
                    await self.build(UnitTypeId.GATEWAY, near=pylon)
                return
            else:
                # If we have no cybernetics core, build one
                if not self.structures(UnitTypeId.CYBERNETICSCORE):
                    if self.can_afford(UnitTypeId.CYBERNETICSCORE):
                        await self.build(UnitTypeId.CYBERNETICSCORE, near=pylon)
                        self.cybercore_started = True
                    return
                else:
                    if self.cybercore_started: #TODO: Change to 'cybernetics_core progress > 0'

                        # start two gases when affordable
                        if self.can_afford(UnitTypeId.ASSIMILATOR) and self.structures(UnitTypeId.ASSIMILATOR).amount < 2:
                            vgs = self.vespene_geyser.closer_than(15, nexus)
                            for vg in vgs:
                                if self.can_afford(UnitTypeId.ASSIMILATOR):
                                    worker = self.select_build_worker(vg.position)
                                    if worker is None:
                                        break
                                    worker.build(UnitTypeId.ASSIMILATOR, vg)
                                    worker.stop(queue=True)
                                    break
                    # build a twilight council when affordable
                    if self.structures(UnitTypeId.CYBERNETICSCORE).ready and not self.structures(UnitTypeId.TWILIGHTCOUNCIL):
                        if self.can_afford(UnitTypeId.TWILIGHTCOUNCIL):
                            await self.build(UnitTypeId.TWILIGHTCOUNCIL, near=pylon)
                            return
                                    

        # Research warp gate if cybercore is completed
        if (
            self.structures(UnitTypeId.CYBERNETICSCORE).ready and self.can_afford(AbilityId.RESEARCH_WARPGATE)
            and self.already_pending_upgrade(UpgradeId.WARPGATERESEARCH) == 0
        ):
            ccore = self.structures(UnitTypeId.CYBERNETICSCORE).ready.first
            ccore.research(UpgradeId.WARPGATERESEARCH)

        # Once we are researching warp gate, start a twilight council if we can afford it
        # and if we don't have one already
        if (
            self.structures(UnitTypeId.TWILIGHTCOUNCIL).ready and self.can_afford(AbilityId.RESEARCH_CHARGE)
            and self.already_pending_upgrade(UpgradeId.CHARGE) == 0
        ):
            twilight = self.structures(UnitTypeId.TWILIGHTCOUNCIL).ready.first
            twilight.research(UpgradeId.CHARGE)

        # If gate way is done, make zealots
        if self.structures(UnitTypeId.GATEWAY).ready:
            gateway = self.structures(UnitTypeId.GATEWAY).ready.random
            if self.can_afford(UnitTypeId.ZEALOT) and gateway.is_idle:
                # if warp gate is done, warp in zealots near random pylon near a nexus 
                if self.structures(UnitTypeId.WARPGATE).ready:
                    pylon = self.structures(UnitTypeId.PYLON).ready.random
                    placement = await self.find_placement(UnitTypeId.ZEALOT, pylon.position.to2, placement_step=1)
                    if placement is None:
                        #return ActionResult.CantFindPlacementLocation
                        logger.info("Can't find placement for zealot")
                        return
                    gateway.warp_in(UnitTypeId.ZEALOT, placement)

        # if there is more than 10 zealots, attack
        if self.units(UnitTypeId.ZEALOT).amount > 10:
            for zealot in self.units(UnitTypeId.ZEALOT):
                zealot.attack(self.enemy_start_locations[0])


        if self.worker_to_mineral_patch_dict:
            # Quick-access cache mineral tag to mineral Unit
            minerals: Dict[int, Unit] = {mineral.tag: mineral for mineral in self.mineral_field}

            for worker in self.workers:
                if not self.townhalls:
                    logger.error("All townhalls died - can't return resources")
                    break

                worker: Unit
                
                # Check if worker's tag exists in the dictionary
                if worker.tag in self.worker_to_mineral_patch_dict:
                    mineral_tag = self.worker_to_mineral_patch_dict[worker.tag]
                    mineral = minerals.get(mineral_tag, None)
                else:
                    # Handle the case where the worker's tag doesn't exist in the dictionary.
                    await self.assign_worker_to_mineral_patch(worker)
                    mineral_tag = self.worker_to_mineral_patch_dict.get(worker.tag, None)
                    if mineral_tag is None:
                        logger.error(f"Failed to assign worker with tag {worker.tag} to a mineral patch")
                        continue
                
                if mineral_tag is None:
                    logger.error(f"Worker with tag {worker.tag} has no mineral patch assigned")
                else:
                    mineral = minerals.get(mineral_tag, None)
                    continue

                if mineral is None:
                    logger.error(f"Mined out mineral with tag {mineral_tag} for worker {worker.tag}")
                    continue

                # Order worker to mine at target mineral patch if isn't carrying minerals
                if not worker.is_carrying_minerals:
                    if not worker.is_gathering or worker.order_target != mineral.tag:
                        worker.gather(mineral)
                # Order worker to return minerals if carrying minerals
                else:
                    th = self.townhalls.closest_to(worker)
                    # Move worker in front of the nexus to avoid deceleration until the last moment
                    if worker.distance_to(th) > th.radius + worker.radius + self.townhall_distance_threshold:
                        pos: Point2 = th.position
                        worker.move(pos.towards(worker, th.radius * self.townhall_distance_factor))
                        worker.return_resource(queue=True)
                    else:
                        worker.return_resource()
                        worker.gather(mineral, queue=True)      

        # Print info every 30 game-seconds
        if self.state.game_loop % (22.4 * 30) == 0:
            logger.info(f"{self.time_formatted} Mined a total of {int(self.state.score.collected_minerals)} minerals")


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