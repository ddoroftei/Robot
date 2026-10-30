"""
arbitrage.py - Logica automata de arbitraj la granularitate de 15 minute

Lucreaza cu 96 de intervale pe zi (x15 min) de la OPCOM.
Determina automat care intervale sunt ieftine (incarcare) si
care sunt scumpe (descarcare), fara praguri manuale.

Slot-uri: 0-95
  slot 0  = 00:00-00:15
  slot 4  = 01:00-01:15
  slot 95 = 23:45-24:00
"""

from dataclasses import dataclass, field
from typing import Dict, List
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def slot_to_time(slot: int) -> str:
    """Slot 0-95 → 'HH:MM'. Ex: 0→'00:00', 6→'01:30', 95→'23:45'"""
    return f"{slot // 4:02d}:{(slot % 4) * 15:02d}"


def slot_end_time(slot: int) -> str:
    """Ora de sfarsit a unui slot. Slot 95→'24:00'"""
    if slot + 1 == 96:
        return "24:00"
    return slot_to_time(slot + 1)


@dataclass
class ChargeInterval:
    start_slot: int   # 0-95
    end_slot: int     # 1-96 (exclusiv, primul slot din intervalul urmator)
    price: float
    action: str       # "charge" sau "discharge"

    @property
    def start_time(self) -> str:
        return slot_to_time(self.start_slot)

    @property
    def end_time(self) -> str:
        return slot_to_time(self.end_slot) if self.end_slot < 96 else "24:00"

    @property
    def duration_min(self) -> int:
        return (self.end_slot - self.start_slot) * 15

    def __str__(self):
        label = "INCARCARE" if self.action == "charge" else "DESCARCARE"
        return (
            f"[{label}] {self.start_time}-{self.end_time} "
            f"({self.duration_min}min) @ {self.price:.2f} RON/MWh"
        )


@dataclass
class ArbitrageSchedule:
    date: datetime
    charge_intervals: List[ChargeInterval] = field(default_factory=list)
    discharge_intervals: List[ChargeInterval] = field(default_factory=list)
    prices: Dict[int, float] = field(default_factory=dict)
    avg_price: float = 0.0
   

    @property
    def estimated_spread(self) -> float:
        if not self.charge_intervals or not self.discharge_intervals:
            return 0.0
        avg_c = sum(i.price for i in self.charge_intervals) / len(self.charge_intervals)
        avg_d = sum(i.price for i in self.discharge_intervals) / len(self.discharge_intervals)
        return avg_d - avg_c

    def summary(self) -> str:
        lines = [
            f"\n{'='*60}",
            f"PROGRAM ARBITRAJ - {self.date.strftime('%d.%m.%Y')} (intervale 15min)",
            f"{'='*60}",
            f"  Media zilei:      {self.avg_price:.2f} RON/MWh",
           
        ]

        if self.charge_intervals:
            lines.append(f"\n🔋 INCARCARE DIN RETEA:")
            for i in self.charge_intervals:
                lines.append(f"   {i}")
        else:
            lines.append("\n⚠️  Nicio incarcare identificata")

        if self.discharge_intervals:
            lines.append(f"\n⚡ DESCARCARE IN RETEA:")
            for i in self.discharge_intervals:
                lines.append(f"   {i}")
        else:
            lines.append("\n⚠️  Nicio descarcare rentabila")

        if self.estimated_spread > 0:
            lines.append(f"\n📊 Spread estimat: {self.estimated_spread:.2f} RON/MWh")
        else:
            lines.append(f"\n⚠️  Arbitrajul nu pare rentabil azi")

        lines.append(f"{'='*60}")
        return "\n".join(lines)


class ArbitrageEngine:
    """
    Determina automat intervalele de 15 min pentru incarcare/descarcare.
    Nu necesita praguri manuale - se bazeaza pe media zilei.
    """

    def __init__(self, battery_efficiency: float = 0.90):
        self.battery_efficiency = battery_efficiency

    def calculate_schedule(
        self,
        prices: Dict[int, float],
        date: datetime = None
    ) -> ArbitrageSchedule:
        """
        Args:
            prices: Dict { slot 0-95: pret RON/MWh }
        """
        if date is None:
            date = datetime.now()

        schedule = ArbitrageSchedule(date=date, prices=prices)

        if not prices:
            logger.warning("Nu exista preturi disponibile!")
            return schedule

        avg_price = sum(prices.values()) / len(prices)
        

        schedule.avg_price = avg_price
        

        logger.info(
            f"Media: {avg_price:.2f} RON/MWh | "
            f"Intervale disponibile: {len(prices)}/96"
        )

        # Sloturi pentru incarcare: sub media zilei
        charge_slots = sorted(
            [s for s, p in prices.items() if p <= avg_price * 0.85]
        )

        # Sloturi pentru descarcare: peste pragul de rentabilitate
        discharge_slots = sorted(
            [s for s, p in prices.items() if p >= avg_price * 1.30]
        )

        # Elimina overlap (un slot nu poate fi si charge si discharge)
        discharge_slots = [s for s in discharge_slots if s not in charge_slots]

        logger.info(
            f"Sloturi incarcare: {len(charge_slots)} | "
            f"Sloturi descarcare: {len(discharge_slots)}"
        )

        schedule.charge_intervals = self._group_into_intervals(
            charge_slots, prices, "charge"
        )
        schedule.discharge_intervals = self._group_into_intervals(
            discharge_slots, prices, "discharge"
        )

        return schedule

    def _group_into_intervals(
        self,
        slots: List[int],
        prices: Dict[int, float],
        action: str
    ) -> List[ChargeInterval]:
        """Grupeaza sloturi consecutive de 15min in intervale continue."""
        if not slots:
            return []

        intervals = []
        start = slots[0]
        end = slots[0]

        for i in range(1, len(slots)):
            if slots[i] == end + 1:
                end = slots[i]
            else:
                avg_p = sum(prices.get(s, 0) for s in range(start, end + 1)) / (end - start + 1)
                intervals.append(ChargeInterval(start, end + 1, avg_p, action))
                start = slots[i]
                end = slots[i]

        avg_p = sum(prices.get(s, 0) for s in range(start, end + 1)) / (end - start + 1)
        intervals.append(ChargeInterval(start, end + 1, avg_p, action))

        return intervals

    def to_dulink_format(self, schedule: ArbitrageSchedule) -> List[Dict]:
        """
        Converteste in format Dulink - UN RAND per slot de 15 minute.

        Ex: in loc de un calup 00:00→05:15, genereaza randuri individuale:
          00:00→00:15 Charge
          00:15→00:30 Charge
          ...
          05:00→05:15 Charge
        """
        
        settings = []

        for interval in schedule.charge_intervals:
            settings.append({
                "start_time": interval.start_time,
                "end_time": interval.end_time,
                "mode": "charge",
                "price": interval.price,
            })

        for interval in schedule.discharge_intervals:
            settings.append({
                "start_time": interval.start_time,
                "end_time": interval.end_time,
                "mode": "discharge",
                "price": interval.price,
            })

        settings.sort(key=lambda x: x["start_time"])
        return settings