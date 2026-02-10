'use client';

import React from 'react';
import { WerewolfPlayer } from '@/store/types';
import { getWerewolfSeatPosition } from './layoutUtils';
import { motion } from 'framer-motion';
import { Moon, Sun, Skull } from 'lucide-react';

interface GodViewBoardProps {
  players: WerewolfPlayer[];
}

export default function GodViewBoard({ players }: GodViewBoardProps) {
  return (
    <div className="absolute inset-0">
      {players.map((player, idx) => {
        const pos = getWerewolfSeatPosition(idx, players.length, 40); // 40% radius
        
        // Determine Role Icon
        let roleIcon = <span className="text-xs">?</span>;
        let ringColor = 'border-gray-600';
        
        // If role is object or string
        const roleName = typeof player.role === 'string' ? player.role : player.role?.name;
        
        if (roleName === 'Werewolf') {
          roleIcon = <Moon size={16} className="text-red-500" />;
          ringColor = 'border-red-500 shadow-[0_0_10px_rgba(239,68,68,0.5)]';
        } else if (roleName === 'Seer') {
          roleIcon = <Sun size={16} className="text-purple-500" />;
          ringColor = 'border-purple-500 shadow-[0_0_10px_rgba(168,85,247,0.5)]';
        } else if (roleName === 'Villager') {
          roleIcon = <span className="text-xs text-blue-300">V</span>;
          ringColor = 'border-blue-500';
        }

        if (!player.is_alive) {
          roleIcon = <Skull size={16} className="text-gray-500" />;
          ringColor = 'border-gray-700 grayscale opacity-50';
        }

        return (
          <motion.div
            key={player.sid}
            className="absolute w-24 h-24 flex flex-col items-center justify-center z-20"
            style={{ left: pos.x, top: pos.y, transform: 'translate(-50%, -50%)' }}
            initial={{ scale: 0 }}
            animate={{ scale: 1 }}
          >
            {/* Avatar */}
            <div className={`w-14 h-14 rounded-full bg-gray-900 border-2 ${ringColor} flex items-center justify-center relative`}>
              {roleIcon}
              <div className="absolute -bottom-1 -right-1 w-5 h-5 bg-black rounded-full flex items-center justify-center border border-gray-700 text-[10px] text-white">
                {idx + 1}
              </div>
            </div>
            
            {/* Name */}
            <div className="mt-1 bg-black/80 px-2 py-0.5 rounded text-[10px] text-white truncate max-w-full border border-gray-800">
              {player.nickname}
            </div>
          </motion.div>
        );
      })}
    </div>
  );
}
