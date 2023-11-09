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
# import alerts
from sc2.game_info import GameInfo
from sc2.game_state import GameState
from sc2.client import Client

import random

class ZealotChargeBot(BotAI):
    """
    This bot aims to produce zealots and research Charge, then attack with them.
    Steps:
    1. Build workers and gather resources.
    2. Build Pylons, Gateways, and a Twilight Council.
    3. Research Zealot Charge.
    4. Train Zealots.
    5. Attack the enemy.
    """

    """
    TODO: 
    - Build a Forge and research +1 Armor
    - Add Production:
        - Gateways
        - Zealots
    - Scouting logic
    - Attack logic
    - Defense logic

    Small Fixes
    - Make sure workers return resources before starting to build or mine/start another order

    """
    
    def __init__(self):
        super().__init__()
        self.charge_researched = False

        # Reusing the mining optimization attributes
        self.worker_to_mineral_patch_dict = {}
        self.mineral_patch_to_list_of_workers = {}

        self.minerals_sorted_by_distance = []
        self.townhall_distance_threshold = 0.15
        self.townhall_distance_factor = 1
        self.worker_to_nexus_dict: Dict[int, int] = {}
        self.builders = set()
        self.scouts = set()
        #workers mining vespene
        self.workers_mining_vespene = set()

        # Additional attributes for our Zealot Charge Bot
        self.assimilator_started = False
        self.twilight_started = False
        self.scout_fleeing = False

        self.max_probes = 55    # Maximum number of probes to produce
        self.supply_buffer = 5  # supply buffer
        self.max_nexus = 3      # max nexus
        self.max_gateways = 16   # max gateways
        self.max_assimilators = 1 # number of assimilators to build

    async def on_start(self):
        self.client.game_step = 1
        await self.chat_send("(glhf)")
        await self.assign_initial_workers()

        # DEBUG
        #await self.client.debug_fast_build()
        #await self.client.debug_all_resources()
 
    async def on_step(self, iteration: int):
        #await self.distribute_workers()        # For general worker distribution (replaced by our own logic)

        await self.scout_with_zealot()          # Scout with Zealot
        await self.train_zealots()              # Train Zealots

        await self.check_for_idle_workers()     # Check for idle workers
        await self.manage_worker_task()         # Our worker logic
        await self.manage_gas()                 # Our gas logic

        await self.build_order()                # Our building logic
    
        await self.build_pylon()                # Build Pylons if we are low
        await self.manage_chrono_boost()        # Manage Chrono Boost

        await self.logs()                       # Log for debugging

    # Logging for debugging
    async def logs(self):

        all_logs = False
        # Every 10 seconds print these logs
        if self.time % 10 == 0:
            
            logger.warning("======================== LOG INFO ========================")
            # time elapsed
            logger.info(f"Time elapsed: {self.time}(s)")
            logger.info(f"Builders: {self.builders}")

            if all_logs:
                logger.info(f"Worker to Nexus: {self.worker_to_nexus_dict}")
                # idle workers
                logger.info(f"Idle workers: {self.workers.idle.amount}")
                # idle worker ids
                logger.info(f"Idle worker ids: {[worker.tag for worker in self.workers.idle]}")
                # log nexuses and their ids as well as their ideal harvesters and assigned harvesters
                # nexus count
                logger.warning("======================== NEXUS INFO ========================")
                logger.info(f"Nexus count: {self.townhalls.amount}")
                logger.info(f"Nexuses: {self.townhalls}")
                logger.info(f"Nexus ids: {[nexus.tag for nexus in self.townhalls]}")
                logger.info(f"Nexus ideal harvesters: {[nexus.ideal_harvesters for nexus in self.townhalls]}")
                logger.info(f"Nexus assigned harvesters: {[nexus.assigned_harvesters for nexus in self.townhalls]}")
            
                # get game state
                alerts = self.state.alerts
                action_errors = self.state.action_errors
                if alerts:
                    logger.warning(f"Alerts: {alerts}")
                if action_errors:
                    logger.warning(f"Action Errors: {action_errors}")

    async def scout_with_zealot(self):
        # If no Zealots exist, use a Probe to scout
        if not self.units(UnitTypeId.ZEALOT):
            return
        # If we have no scout yet, assign the first zealot as a scout
        if not self.scouts:
            zealots = self.units(UnitTypeId.ZEALOT)
            if zealots:  # If there is at least one zealot
                scout = zealots.first
                self.scouts.add(scout.tag)
                self.prev_scout_shield = scout.shield  # Store the shield value for the next iteration
                # Send the scout to the enemy's starting location
                await self.issue_scouting_orders(scout)
        else:
            # If we already have a scout, we will continue to issue scouting orders
            for tag in self.scouts:
                scout = self.units.find_by_tag(tag)
                if scout:
                        # Issue scouting orders, e.g., move to various enemy expansions
                        await self.issue_scouting_orders(scout)

    async def issue_scouting_orders(self, scout):
        # If the scout is fleeing, check if it is safe to stop fleeing
        if self.scout_fleeing:
            if scout.shield == scout.shield_max:  # Scout has regenerated shields
                self.scout_fleeing = False
                logger.info(f"Scout {scout.tag} has regenerated shields. Resuming scouting.")
                scout.stop() 
            else:
                return  # Continue fleeing until fully regenerated
        if scout.is_attacking and scout.shield < self.prev_scout_shield-5:
            return  # Continue attacking until the enemy is dead

        if scout.is_idle:
            # Move to a point that's within the Zealot's vision range of the enemy's start location
            safe_distance_point = self.enemy_start_locations[0].towards(self.start_location, scout.sight_range)
            scout.move(safe_distance_point)
            logger.info(f"Scout {scout.tag} is cautiously moving to {safe_distance_point}")

        if scout:
            # Check for enemies in sight range
            enemies_in_sight = self.enemy_units.filter(lambda unit: unit.can_be_attacked and unit.is_visible)
            if enemies_in_sight:
                logger.info(f"Scout {scout.tag} has sighted {len(enemies_in_sight)} enemies")
                # Log detailed information about each enemy in sight
                for enemy in enemies_in_sight:
                    logger.info(f"Scout {scout.tag} has sighted enemy {enemy.type_id} with tag {enemy.tag} at {enemy.position}")
                    if enemy.can_attack:  # If the enemy can attack, log its range and dps
                        logger.info(f"Enemy {enemy.type_id} with tag {enemy.tag} has range {enemy.ground_range} and DPS {enemy.calculate_dps_vs_target(scout)}")
                # Choose an enemy to move towards or observe
                target = enemies_in_sight.closest_to(scout)
                observation_point = target.position.towards(scout, scout.sight_range)
                scout.move(observation_point)
                logger.info(f"Scout {scout.tag} is moving to observe {target.type_id} at {observation_point}")
                logger.warning("INFO ABOUT OBSERVATION TARGET: ")
                # log the enemy target
                logger.warning(f"Enemy target: {target.tag} at {target.position} of type {target.type_id}")
                # potential dps of the enemy target
                logger.warning(f"DPS of scout vs target: {scout.calculate_dps_vs_target(target)}")
                # potential dps of the scout
                logger.warning(f"DPS of target vs scout: {target.calculate_dps_vs_target(scout)}")
                # targets range
                logger.warning(f"Target range: {target.ground_range}")
                # scouts range
                logger.warning(f"Scout range: {scout.ground_range}")
                # target in range of scout
                logger.warning(f"Target in range of scout? {scout.target_in_range(target)}")
                # scout in range of target
                logger.warning(f"Scout in range of target? {target.target_in_range(scout)}")
                # if the target is a worker, attack it
                if target.type_id == UnitTypeId.PROBE or target.type_id == UnitTypeId.SCV or target.type_id == UnitTypeId.DRONE:
                    logger.warning(f"Target is a worker. Attacking...")
                    scout.attack(target)


            # Check if the scout is being attacked by comparing its current shield with its shield in the last step
            if scout.shield < self.prev_scout_shield:
                logger.warning(f"Scout {scout.tag} is being attacked. Moving away... Shield: {scout.shield}/{scout.shield_max}")
                # Move away towards a nexus
                flee_position = self.townhalls.closest_to(scout).position.towards(scout, 5)
                scout.move(flee_position)
                self.scout_fleeing = True
                logger.info(f"Scout {scout.tag} is fleeing to {flee_position}")

            # Update the previous shield value for the next iteration
            self.prev_scout_shield = scout.shield

    # Move zealots to our ramp
    async def move_zealots_to_ramp(self):
        # If we have zealots, move them to our ramp
        if self.units(UnitTypeId.ZEALOT):
            # if its not a scouting zealot, move it to the ramp
            for zealot in self.units(UnitTypeId.ZEALOT):
                if zealot.tag not in self.scouts:
                    # if charge is done, attack the enemy
                    if self.already_pending_upgrade(UpgradeId.CHARGE) == 1 and len(self.units(UnitTypeId.ZEALOT)) >= 25:
                        # if we have a target, attack it
                        if self.enemy_units:
                            # compare enemy units to our zealots
                            
                            target = self.enemy_units.closest_to(zealot)
                            zealot.attack(target)
                            logger.warning(f"Zealot {zealot.tag} is attacking {target.type_id} at {target.position}")
                            # check if we can beat the enemy units with ours
                            if zealot.calculate_dps_vs_target(target) < target.calculate_dps_vs_target(zealot) and target.calculate_speed() < zealot.calculate_speed():
                                logger.warning(f"Zealot {zealot.tag} is retreating (DPS: {zealot.calculate_dps_vs_target(target)} vs {target.calculate_dps_vs_target(zealot)}, Speed: {zealot.calculate_speed()} vs {target.calculate_speed()})")
                                zealot.move(self.townhalls.closest_to(zealot).position)
                        # else move to the enemy start location
                        else:
                            zealot.attack(self.enemy_start_locations[0])
                            logger.warning(f"Zealot {zealot.tag} is attacking enemy start location")
                    else:
                        # move to main nexus
                        zealot.move(self.townhalls.closest_to(zealot).position)

    # Train Zealots
    async def train_zealots(self):
        
        if self.structures(UnitTypeId.WARPGATE).ready.exists and self.can_afford(UnitTypeId.ZEALOT) and self.already_pending_upgrade(UpgradeId.WARPGATERESEARCH) == 1:
            for warpgate in self.structures(UnitTypeId.WARPGATE).ready:
                abilities = await self.get_available_abilities(warpgate)
                if AbilityId.WARPGATETRAIN_ZEALOT in abilities:
                    pylon = self.structures(UnitTypeId.PYLON).ready.random
                    pos = pylon.position.to2.random_on_distance(4)
                    placement = await self.find_placement(AbilityId.WARPGATETRAIN_ZEALOT, pos, placement_step=1)
                    if placement is None:
                        logger.warning(f"Cannot warp in Zealot. Invalid placement location")
                        return
                    warpgate.warp_in(UnitTypeId.ZEALOT, placement)
                    await self.move_zealots_to_ramp()

        # If we have a Gateway and can afford a Zealot, train one if warpgate is not researched
        if self.structures(UnitTypeId.GATEWAY).ready.exists and self.can_afford(UnitTypeId.ZEALOT) and self.already_pending_upgrade(UpgradeId.WARPGATERESEARCH) == 0:
            for gateway in self.structures(UnitTypeId.GATEWAY).ready.idle:
                if gateway.is_idle:
                    gateway.train(UnitTypeId.ZEALOT)
                    await self.move_zealots_to_ramp()
        
    # Manage Chrono Boost
    async def manage_chrono_boost(self):
        # How this works: 
        # 1. If we have a nexus with chrono boost available
        # 2. If we arent researching charge, use it on the nexus (If we have enough supply (supply_buffer-2))
        # 3. If we are researching charge, use on twilight council (no need to check supply)
        if self.structures(UnitTypeId.NEXUS).ready.exists:
            
            for nexus in self.structures(UnitTypeId.NEXUS).ready:
                if nexus.energy >= 50:
                    if self.structures(UnitTypeId.TWILIGHTCOUNCIL).ready.exists:
                            tc = self.structures(UnitTypeId.TWILIGHTCOUNCIL).ready.first
                            if not tc.is_idle:
                                logger.warning(f"Chrono Boosting Twilight Council")
                                nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, tc)
                    elif self.supply_left > self.supply_buffer - 2:
                        nexus(AbilityId.EFFECT_CHRONOBOOSTENERGYCOST, nexus)
                               
    # Worker Manager
    async def produce_probes(self):
        # Check if the total number of probes is less than max_probes
        if self.workers.amount < self.max_probes:
            for nexus in self.townhalls.idle:  # Only idle Nexuses, to prevent overriding other commands
                # Ensure we have enough resources and the Nexus isn't already training a probe
                if self.can_afford(UnitTypeId.PROBE):
                    nexus.train(UnitTypeId.PROBE)

    async def resaturate(self):
        workers_that_have_been_reassigned = set()
        total_workers_needed = sum(nexus.ideal_harvesters for nexus in self.townhalls)
        total_workers_assigned = sum(len(workers) for workers in self.mineral_patch_to_list_of_workers.values())

        if total_workers_assigned == total_workers_needed:
            return  # Early exit if we're already perfectly saturated

        # Calculate the worker distribution only once
        nexus_worker_info = []
        for nexus in self.townhalls:
            if nexus.build_progress < 0.9:  # Skip nexuses that aren't finished
                continue
            workers_on_this_nexus = sum(len(self.mineral_patch_to_list_of_workers.get(mineral.tag, set()))
                                        for mineral in self.mineral_field.closer_than(10, nexus.position))
            nexus_worker_info.append({
                "nexus": nexus,
                "workers_needed": nexus.ideal_harvesters,
                "workers_current": workers_on_this_nexus,
                "oversaturated": workers_on_this_nexus > nexus.ideal_harvesters
            })

        # Sort based on saturation level
        undersaturated_nexuses = sorted((info for info in nexus_worker_info if not info["oversaturated"]),
                                        key=lambda x: x["workers_needed"] - x["workers_current"])
        oversaturated_nexuses = sorted((info for info in nexus_worker_info if info["oversaturated"]),
                                    key=lambda x: x["workers_current"] - x["workers_needed"], reverse=True)

        # Rebalance workers from oversaturated to undersaturated nexuses
        for over_info in oversaturated_nexuses:
            for under_info in undersaturated_nexuses:
                while over_info["workers_current"] > over_info["workers_needed"] and under_info["workers_current"] < under_info["workers_needed"]:
                    # Find an available worker from the oversaturated nexus
                    worker = next((w for w in self.workers if w.tag not in workers_that_have_been_reassigned and w.position.distance_to(over_info["nexus"].position) < 10), None)
                    if worker:
                        await self.assign_worker_to_another_nexus(worker)
                        workers_that_have_been_reassigned.add(worker.tag)
                        over_info["workers_current"] -= 1
                        under_info["workers_current"] += 1
                    else:
                        break  # Break if no available worker is found in the oversaturated nexus

        # Now, assign workers to minerals at undersaturated Nexuses
        for under_info in undersaturated_nexuses:
            while under_info["workers_current"] < under_info["workers_needed"]:
                # Find an available worker
                worker = next((w for w in self.workers if w.tag not in workers_that_have_been_reassigned), None)
                if not worker:
                    logger.warning(f"No available workers to assign to Nexus {under_info['nexus'].tag}")
                    break  # No workers available to assign

                # Find an unassigned mineral patch
                minerals_near_nexus = self.mineral_field.closer_than(10, under_info['nexus'].position).sorted_by_distance_to(under_info['nexus'].position)
                for mineral in minerals_near_nexus:
                    if len(self.mineral_patch_to_list_of_workers.get(mineral.tag, set())) < 2:  # Assuming 2 workers per mineral patch is ideal
                        # Assign the worker to the mineral patch
                        self.mineral_patch_to_list_of_workers.setdefault(mineral.tag, set()).add(worker.tag)
                        self.worker_to_mineral_patch_dict[worker.tag] = mineral.tag
                        # command the worker to gather the mineral
                        worker.gather(mineral)
                        workers_that_have_been_reassigned.add(worker.tag)
                        under_info["workers_current"] += 1
                        break  # Break after assigning one worker

                # If we didn't break, it means no unassigned mineral patch was found
                if under_info["workers_current"] < under_info["workers_needed"]:
                    logger.warning(f"No unassigned mineral patches near Nexus {under_info['nexus'].tag}")
                    break  # No unassigned mineral patches to assign





       
    async def assign_worker_to_another_nexus(self, worker: Unit):
        alternative_nexuses = [nexus for nexus in self.townhalls.sorted_by_distance_to(worker.position) if nexus.is_ready]  # filter for completed nexuses

        # Log if there are no completed Nexuses available.
        if not alternative_nexuses:
            logger.warning(f"No completed Nexuses available to assign worker {worker.tag}.")
            return

        for alternative_nexus in reversed(alternative_nexuses):  # Reverse to get from furthest to closest
            minerals_near_nexus = self.mineral_field.closer_than(10, alternative_nexus.position).sorted_by_distance_to(worker.position)
            logger.warning(f"Assigning worker {worker.tag} to nexus {alternative_nexus.tag}")
            for mineral in minerals_near_nexus:
                
                if len(self.mineral_patch_to_list_of_workers.get(mineral.tag, set())) < 2:
                    self.mineral_patch_to_list_of_workers.setdefault(mineral.tag, set()).add(worker.tag)
                    self.worker_to_mineral_patch_dict[worker.tag] = mineral.tag
                    logger.warning(f"Worker {worker.tag} assigned to mineral patch {mineral.tag} at nexus {alternative_nexus.tag}")
                    worker.gather(mineral)
                    return  # Break out after assigning

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

    async def on_building_construction_complete(self, unit: Unit):
        # Log when a building is completed
        logger.warning(f"Building {unit.type_id} completed at {unit.position}.")
        if unit.type_id == UnitTypeId.NEXUS:
            await self.resaturate()
            # after resaturating, call the initial worker assignment function to recalibrate
            await self.assign_initial_workers()

    async def on_unit_destroyed(self, unit_tag):
        # Log when a unit is destroyed
        logger.warning(f"Unit {unit_tag} destroyed.")
        unit = self._units_previous_map.get(unit_tag)
        if unit and unit.type_id == UnitTypeId.NEXUS:
            await self.resaturate()
        # if it was a scout, remove it from the scouts set
        if unit_tag in self.scouts:
            self.scouts.remove(unit_tag)
        # if it was a builder, remove it from the builders set
        if unit_tag in self.builders:
            self.builders.remove(unit_tag)
    
    async def on_unit_created(self, unit: Unit):
        # Log when a unit is created
        logger.warning(f"Unit {unit.tag} created.")
        # if its a probe and we are at max probes, resaturate
        if unit.type_id == UnitTypeId.PROBE and self.workers.amount >= self.max_probes:
            logger.warning(f"Reached max probes. Resaturating...")
            await self.resaturate()
             # after resaturating, call the initial worker assignment function to recalibrate
            await self.assign_initial_workers()


    # Gas Manager
    # If an assimilator is completed and ready, assign 3 workers to it.
    async def manage_gas(self):
        # check if we have any assimilators
        if self.structures(UnitTypeId.ASSIMILATOR).ready.exists:
            for assimilator in self.structures(UnitTypeId.ASSIMILATOR).ready:
                if assimilator.assigned_harvesters < assimilator.ideal_harvesters:
                    logger.warning(f"Assimilator {assimilator.tag} is not saturated (needs {assimilator.ideal_harvesters - assimilator.assigned_harvesters} more workers.)")
                    workers = self.workers.closer_than(10, assimilator)
        
                    for worker in workers:
                        logger.warning(f"Assigning worker {worker.tag} to assimilator {assimilator.tag}")
                        # if worker is carrying resources, return them
                        if worker.is_carrying_minerals or worker.is_carrying_vespene:
                            logger.warning(f"Worker {worker.tag} is carrying resources. Returning resources before gathering gas")
                            worker.return_resource(queue=False)
                        # remove from builder set if it is in there
                        if worker.tag in self.builders:
                            self.builders.remove(worker.tag)
                        # remove any orders / previous assignments
                        worker.stop(queue=False)
                        logger.warning(f"Worker {worker.tag} is gathering? {worker.is_gathering}")
                        logger.warning(f"Worker {worker.tag} is carrying minerals? {worker.is_carrying_minerals}")
                        # is the geyser valid?
                        logger.warning(f"Assimilator {assimilator.tag} is valid? {assimilator.is_vespene_geyser}")
                        worker.gather(assimilator)
                        self.workers_mining_vespene.add(worker.tag)
                        break
                # else if over saturated, remove workers
                if assimilator.assigned_harvesters > assimilator.ideal_harvesters:
                    logger.error("Assimilator is over saturated. Removing workers...")
                    workers = self.workers.closer_than(10, assimilator)

                    num_workers_to_remove = assimilator.assigned_harvesters - assimilator.ideal_harvesters
                    logger.error(f"Number of workers to remove: {num_workers_to_remove}. TODO: add code to remove these workers.")
                    #TODO : Remove workers from the assimilator
                    for worker in workers:
                        if worker.tag in self.workers_mining_vespene:
                            self.workers_mining_vespene.remove(worker.tag)
                        worker.stop(queue=False)
                        worker.gather(self.mineral_field.closest_to(worker.position))
                        await self.assign_worker_to_mineral_patch(worker)
                        break
                # if charge and warpgate are done, stop mining gas
                if self.already_pending_upgrade(UpgradeId.CHARGE) == 1 and self.already_pending_upgrade(UpgradeId.WARPGATERESEARCH) == 1:
                    logger.warning(f"Charge and Warpgate are done. Removing workers from gas...")
                    workers = self.workers.closer_than(10, assimilator)

                    for worker in workers:
                        if worker.tag in self.workers_mining_vespene:
                            self.workers_mining_vespene.remove(worker.tag)
                        worker.stop(queue=False)
                        worker.gather(self.mineral_field.closest_to(worker.position))
                        await self.assign_worker_to_mineral_patch(worker)
                        break


    async def assign_worker_to_mineral_patch(self, worker: Unit):
        """Assign a worker to a mineral patch."""
        # remove previous assignments
        if worker.orders:
            worker.stop(queue=True)

        logger.info(f"Assigning worker {worker.tag} to mineral patch")
        # Populate the list of minerals sorted by distance if it's empty
        if not self.minerals_sorted_by_distance:
            print("Sorting minerals by distance")
            self.minerals_sorted_by_distance = self.mineral_field.sorted_by_distance_to(self.townhalls.closest_to(worker))
        
        closest_nexus = self.townhalls.closest_to(worker)
        minerals_near_nexus = self.mineral_field.closer_than(10, closest_nexus.position).sorted_by_distance_to(worker.position)
        
        # Remove the worker from any other mineral patch it might be assigned to
        for patch, workers in self.mineral_patch_to_list_of_workers.items():
            if worker.tag in workers:
                workers.remove(worker.tag)

        # Try to assign optimally first
        for mineral in minerals_near_nexus:
            current_workers = self.mineral_patch_to_list_of_workers.get(mineral.tag, set())

            if len(self.mineral_patch_to_list_of_workers.get(mineral.tag, set())) < 2:
                logger.success(f"Number of workers assigned to mineral patch {mineral.tag}: {len(self.mineral_patch_to_list_of_workers.get(mineral.tag, set()))}. (Under 2 workers, Trying to mine optimally...)")
                self.mineral_patch_to_list_of_workers.setdefault(mineral.tag, set()).add(worker.tag)
                self.worker_to_mineral_patch_dict[worker.tag] = mineral.tag
                return

            # If the mineral is over-saturated, try and assign to the next mineral
            if len(current_workers) >= 3:
                logger.error(f"Mineral patch {mineral.tag} is over-saturated. Skipping... (There are already {len(current_workers)} workers assigned to it))")
                continue
            
            current_workers.add(worker.tag)
            self.mineral_patch_to_list_of_workers[mineral.tag] = current_workers
            self.worker_to_mineral_patch_dict[worker.tag] = mineral.tag
            # Add worker to the mineral patch
            logger.success(f"Worker {worker.tag} assigned to mineral patch {mineral.tag} (There are now {len(current_workers)} workers assigned to it))")
            return
                
        # If everything is saturated, assign to the closest mineral for sub-optimal mining
        closest_mineral = self.minerals_sorted_by_distance[0]
        self.mineral_patch_to_list_of_workers.setdefault(closest_mineral.tag, set()).add(worker.tag)
        self.worker_to_mineral_patch_dict[worker.tag] = closest_mineral.tag

        logger.warning(f"Worker {worker.tag} assigned to mineral patch {closest_mineral.tag}")
        logger.info(f"Is the worker mining? {worker.is_gathering}")
        # log worker orders
        logger.warning(f"Worker {worker.tag} orders: {worker.orders}")

    # Manage mineral workers: Optimized mining to avoid deceleration
    async def manage_worker_task(self):
        # Handle worker to mineral/gas assignments
        minerals: Dict[int, Unit] = {mineral.tag: mineral for mineral in self.mineral_field}

        for worker in self.workers:
            if worker.tag in self.builders or worker.tag in self.workers_mining_vespene:
                continue  # Don't interfere with builders or vespeen workers

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

            if not worker.is_carrying_minerals and not worker.is_carrying_vespene and worker.tag not in self.workers_mining_vespene:
                if mineral and (not worker.is_gathering or worker.order_target != mineral.tag):
                    worker.gather(mineral)

            else:
                if mineral:
                    if not worker.is_gathering or worker.order_target != mineral.tag:
                        worker.gather(mineral)

                th = self.townhalls.closest_to(worker)

                # if the base is not oversaturated,
                if th.assigned_harvesters < th.ideal_harvesters:
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
                else:
                    # If the base is oversaturated, move the worker to the nearest mineral patch
                    worker.return_resource()
                    if mineral:
                        worker.gather(mineral, queue=True)
                    else:
                        await self.assign_worker_to_mineral_patch(worker)

    # Check for idle workers (not gathering minerals or gas and not building anything)
    async def check_for_idle_workers(self):
        for worker in self.workers.idle:
            logger.warning(f"Worker {worker.tag} is idle")
            worker.stop(queue=True)
            if worker.tag not in self.worker_to_mineral_patch_dict:
                logger.warning(f"Worker {worker.tag} is not assigned to a mineral patch. Assigning...")
                await self.assign_worker_to_mineral_patch(worker)
            else:
                logger.warning(f"Idle Worker {worker.tag} is assigned to mineral patch {self.worker_to_mineral_patch_dict[worker.tag]}. Sending to mine...")
                mineral_tag = self.worker_to_mineral_patch_dict[worker.tag]
                mineral = self.mineral_field.find_by_tag(mineral_tag)
                worker.gather(mineral, queue=True)
            # if its a builder, remove it from the builders set
            if worker.tag in self.builders:
                logger.warning(f"Idle Worker {worker.tag} is a builder. Removing from builders set")
                self.builders.remove(worker.tag)
                # send it to mine
                await self.assign_worker_to_mineral_patch(worker)
        # Check for builders that arent building anything
        for worker in self.workers.tags_in(self.builders):
            if not worker.orders and worker.tag in self.builders:
                # log any orders that the worker has
                logger.warning(f"No orders. Orders: {worker.orders} Is Idle? {worker.is_idle}")
                self.builders.remove(worker.tag)

    # Supply Manager
    async def build_pylon(self):
        # Check if there's enough supply or a pylon is already pending
        if self.supply_left >= 5 or self.already_pending(UnitTypeId.PYLON):
            return

        # Check for available nexuses
        if not self.townhalls.ready.exists:
            logger.warning("No nexuses found. Skipping building pylon...")
            return

        # Select the nexus to build near
        nexus = self.townhalls.ready.sorted_by_distance_to(self.enemy_start_locations[0]).first

        # Select a worker from builders or get a new one
        worker = None
        if self.builders:
            worker_tag = random.choice(list(self.builders))
            worker = self.workers.find_by_tag(worker_tag)
            if not worker:
                logger.info("Selected builder not found in the worker pool. Selecting a new worker.")
            elif worker.orders and worker.orders[0].ability.id not in [AbilityId.MOVE, AbilityId.HARVEST_GATHER, AbilityId.HARVEST_RETURN]:
                logger.info(f"Selected builder {worker.tag} is busy. Selecting a new worker.")
                worker = None

        if not worker:
            worker = self.select_build_worker(nexus.position)
            if not worker:
                logger.warning("No available workers to build. Skipping building pylon...")
                return

        # Queue resource return if the worker is carrying resources
        if worker.is_carrying_resource:
            worker.return_resource(queue=True)

        # Build the pylon
        build_position = nexus.position.towards(self.game_info.map_center, 5)
        # make sure the build position is not near another pylon or nexus
        
        await self.build(UnitTypeId.PYLON, near=build_position, build_worker=worker, placement_step=1)

        # Add worker to builders to prevent reassignment
        self.builders.add(worker.tag)


    async def build_order(self):
        if not self.townhalls:  # No Nexus means probably the end of the game
            return
        
        # Get worker to build structures if there are no builders
        if self.builders:
            # get a builder from the set of builders
            worker = self.workers.find_by_tag(random.choice(list(self.builders)))
            if not worker:
                logger.warning("No builders currently (in the builders set)")
                return
        else:
            worker = self.select_build_worker(self.townhalls.first.position)
            # if worker is holding resources, return them
            if worker:
                if worker.is_carrying_minerals or worker.is_carrying_vespene:
                    worker.return_resource(queue=False)
            elif worker:
                # add to builders to prevent interference with worker to mineral assignments
                self.builders.add(worker.tag)
            else:
                logger.warning(f"No workers available to build (in the select_build_worker function)")
                return
        
        if worker and worker.orders and worker.orders[0].ability.id not in [AbilityId.MOVE, AbilityId.HARVEST_GATHER, AbilityId.HARVEST_RETURN]:
            # return resources before building if the worker is carrying resources
            if worker.is_carrying_minerals or worker.is_carrying_vespene:
                # check if the worker doesnt already have this order in the queue
                if AbilityId.HARVEST_RETURN not in [order.ability.id for order in worker.orders]:
                    logger.warning(f"HARVEST RETURN order not found for worker: {worker.tag}. Attempting to return resources before building...")
                    worker.return_resource(queue=True) # queue the order
                else:
                    logger.warning(f"Worker {worker.tag} is already returning resources. Skipping...")
                    return
        # if worker is not in the builders set, add it
        if worker.tag not in self.builders:
            self.builders.add(worker.tag)

        # Always ensure we are training Probes when possible
        for nexus in self.townhalls.ready.idle:
            if self.can_afford(UnitTypeId.PROBE) and self.workers.amount < self.max_probes:
                nexus.train(UnitTypeId.PROBE)

        # If no Pylon, build one
        if not self.structures(UnitTypeId.PYLON) and self.can_afford(UnitTypeId.PYLON):
            await self.build(UnitTypeId.PYLON, near=self.start_location.towards(self.game_info.map_center, 5), build_worker=worker)
        
        # If no Gateway and we have a Pylon, build Gateway
        elif not self.already_pending(UnitTypeId.GATEWAY) and self.can_afford(UnitTypeId.GATEWAY) and self.structures(UnitTypeId.PYLON).ready.exists and not self.structures(UnitTypeId.GATEWAY).ready.exists:
            pylon = self.structures(UnitTypeId.PYLON).ready.random
            await self.build(UnitTypeId.GATEWAY, near=pylon, build_worker=worker)

        # If no Cybernetics Core and we have a Gateway, build Cybernetics Core
        elif not self.structures(UnitTypeId.CYBERNETICSCORE) and self.structures(UnitTypeId.GATEWAY).ready.exists and self.can_afford(UnitTypeId.CYBERNETICSCORE) and not self.already_pending(UnitTypeId.CYBERNETICSCORE):
            pylon = self.structures(UnitTypeId.PYLON).ready.random
            await self.build(UnitTypeId.CYBERNETICSCORE, near=pylon, build_worker=worker)

        # TODO: Expand to a new base if we have enough minerals and probes
        # If we have enough minerals and probes, expand to a new base
        if self.can_afford(UnitTypeId.NEXUS) and self.townhalls.amount < self.max_nexus and self.structure_type_build_progress(UnitTypeId.ASSIMILATOR) > 0.1: # and self.workers.amount > self.townhalls.amount * 16 #Add this for less greed (expand later)
            # use our worker to build a nexus at the next expansion location
            # find next expansion location
            next_expansion_location = await self.get_next_expansion()
            logger.warning(f"Next expansion location: {next_expansion_location}")
            logger.warning(f"Worker status before building: {worker.orders}")
            # build nexus
            worker.stop(queue=False)
            worker.build(UnitTypeId.NEXUS, next_expansion_location)
            logger.warning(f"Worker status after building: {worker.orders}")
   
        # If no Assimilators, build them
        if self.already_pending(UnitTypeId.ASSIMILATOR) < self.max_assimilators and not self.assimilator_started and self.structure_type_build_progress(UnitTypeId.CYBERNETICSCORE) > 0.3:

            for vg in self.vespene_geyser.closer_than(15, self.start_location):
                if not self.can_afford(UnitTypeId.ASSIMILATOR):
                    break
                if worker is None:
                    break
                worker.stop(queue=False)
                worker.build(UnitTypeId.ASSIMILATOR, vg)
                logger.warning(f"Worker {worker.tag} is building an assimilator at {vg.position}")

                # check assimilator construction progress
                if self.structure_type_build_progress(UnitTypeId.ASSIMILATOR) > 0:
                    logger.info(f"Assimilator construction progress: {self.structure_type_build_progress(UnitTypeId.ASSIMILATOR)} Setting to started...")
                    self.assimilator_started = True
                # gather minerals after building
                await self.assign_worker_to_mineral_patch(worker)

        # Once Cybernetics Core is done, if no Twilight Council, build it
        if not self.twilight_started and self.structures(UnitTypeId.CYBERNETICSCORE).ready.exists and self.can_afford(UnitTypeId.TWILIGHTCOUNCIL):
            pylon = self.structures(UnitTypeId.PYLON).ready.random
            await self.build(UnitTypeId.TWILIGHTCOUNCIL, near=pylon, build_worker=worker)
            self.twilight_started = True
            await self.assign_worker_to_mineral_patch(worker)
            
        # If Twilight Council is ready, research Zealot Charge
        if self.structures(UnitTypeId.TWILIGHTCOUNCIL).ready.exists:
            tc = self.structures(UnitTypeId.TWILIGHTCOUNCIL).ready.first
            if self.can_afford(UpgradeId.CHARGE) and not self.already_pending_upgrade(UpgradeId.CHARGE):
                tc.research(UpgradeId.CHARGE)

        # If Charge is researching, research warp gate when possible
        if self.structures(UnitTypeId.TWILIGHTCOUNCIL).ready.exists and self.already_pending_upgrade(UpgradeId.CHARGE):
            cc = self.structures(UnitTypeId.CYBERNETICSCORE).ready.first
            if self.can_afford(UpgradeId.WARPGATERESEARCH) and not self.already_pending_upgrade(UpgradeId.WARPGATERESEARCH):
                cc.research(UpgradeId.WARPGATERESEARCH)

        # Once on max_bases build gateways to max_gateways
        if self.townhalls.amount >= self.max_nexus and self.structures(UnitTypeId.GATEWAY).amount <= self.max_gateways and self.can_afford(UnitTypeId.GATEWAY):
            # find a position near a pylon thats not in the mineral line that a gateway can be built
            pylon = self.structures(UnitTypeId.PYLON).ready.random
            await self.build(UnitTypeId.GATEWAY, near=pylon, build_worker=worker)

    
def main():
    run_game(
        maps.get("AbyssalReefLE"),
        [Bot(Race.Protoss, ZealotChargeBot()),
         Computer(Race.Terran, Difficulty.VeryHard)],
        realtime=True,
        random_seed=0,
    )

if __name__ == "__main__":
    main()
