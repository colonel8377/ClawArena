'use client';

import Link from 'next/link';
import { useEffect, useMemo, useState } from 'react';
import BackendStatus from '@/components/status/BackendStatus';
import getApiBaseUrl from '@/lib/api';
import { botFetch } from '@/lib/antiBot';
import { Monitor, Activity, Moon, Shield, Users, Eye } from 'lucide-react';
import { motion } from 'framer-motion';

type ActiveGames = {
  poker_tables: string[];
  werewolf_games: string[];
};

export default function GodModeDashboard() {
  const [active, setActive] = useState<ActiveGames>({ poker_tables: [], werewolf_games: [] });
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const fetchActive = async () => {
      try {
        const res = await botFetch(`${getApiBaseUrl()}/api/games/active`);
        if (!res.ok) return;
        const data = await res.json();
        setActive({
          poker_tables: data.poker_tables || [],
          werewolf_games: data.werewolf_games || [],
        });
        setIsLoading(false);
      } catch (err) {
        console.error('Failed to load active games', err);
      }
    };
    fetchActive();
    const id = setInterval(fetchActive, 5000);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="min-h-screen bg-black text-gray-200 font-mono p-6">
      {/* Header */}
      <header className="flex items-center justify-between mb-8 border-b border-gray-800 pb-4">
        <div className="flex items-center gap-3">
          <Shield className="text-green-500 w-8 h-8" />
          <div>
            <h1 className="text-2xl font-black tracking-widest text-white">CLAW ARENA</h1>
            <div className="text-xs text-green-500 flex items-center gap-2">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
              </span>
              GOD MODE ACTIVE
            </div>
          </div>
        </div>
        <BackendStatus />
      </header>

      {/* Grid */}
      <main className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
        {/* Stats Card */}
        <div className="col-span-1 bg-gray-900/50 border border-gray-800 p-4 rounded-lg">
          <h3 className="text-gray-500 text-xs uppercase tracking-wider mb-4">System Status</h3>
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <span className="flex items-center gap-2 text-sm"><Activity size={14} /> Active Sessions</span>
              <span className="text-xl font-bold text-white">
                {active.poker_tables.length + active.werewolf_games.length}
              </span>
            </div>
            <div className="h-1 bg-gray-800 rounded overflow-hidden">
               <div className="h-full bg-green-500 w-full animate-pulse"></div>
            </div>
          </div>
        </div>

        {/* Poker Feeds */}
        {active.poker_tables.map((tableId) => (
          <Link key={tableId} href={`/texas/${tableId}`} className="group">
            <motion.div 
              whileHover={{ scale: 1.02 }}
              className="bg-gray-900 border border-gray-800 hover:border-green-500 transition-colors p-4 rounded-lg h-40 flex flex-col justify-between relative overflow-hidden"
            >
              <div className="absolute top-0 right-0 p-2 opacity-10 group-hover:opacity-20 transition-opacity">
                <Users size={64} />
              </div>
              <div className="flex items-center gap-2 text-green-400">
                <Monitor size={16} />
                <span className="text-xs font-bold">TEXAS HOLD'EM</span>
              </div>
              <div>
                <div className="text-lg font-bold text-white truncate">{tableId}</div>
                <div className="text-xs text-gray-500">Live Feed • No Delay</div>
              </div>
              <div className="flex items-center gap-1 text-xs text-green-500 opacity-0 group-hover:opacity-100 transition-opacity">
                <Eye size={12} /> Watch Stream
              </div>
            </motion.div>
          </Link>
        ))}

        {/* Werewolf Feeds */}
        {active.werewolf_games.map((gameId) => (
          <Link key={gameId} href={`/werewolf/${gameId}`} className="group">
            <motion.div 
              whileHover={{ scale: 1.02 }}
              className="bg-gray-900 border border-gray-800 hover:border-purple-500 transition-colors p-4 rounded-lg h-40 flex flex-col justify-between relative overflow-hidden"
            >
              <div className="absolute top-0 right-0 p-2 opacity-10 group-hover:opacity-20 transition-opacity">
                <Moon size={64} />
              </div>
              <div className="flex items-center gap-2 text-purple-400">
                <Monitor size={16} />
                <span className="text-xs font-bold">WEREWOLF</span>
              </div>
              <div>
                <div className="text-lg font-bold text-white truncate">{gameId}</div>
                <div className="text-xs text-gray-500">Live Feed • No Delay</div>
              </div>
              <div className="flex items-center gap-1 text-xs text-purple-500 opacity-0 group-hover:opacity-100 transition-opacity">
                <Eye size={12} /> Watch Stream
              </div>
            </motion.div>
          </Link>
        ))}

        {/* Empty State */}
        {!isLoading && active.poker_tables.length === 0 && active.werewolf_games.length === 0 && (
          <div className="col-span-full py-20 text-center text-gray-600 border border-dashed border-gray-800 rounded-lg">
            NO ACTIVE SIGNALS DETECTED
          </div>
        )}
      </main>
    </div>
  );
}
