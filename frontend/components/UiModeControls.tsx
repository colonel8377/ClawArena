'use client';
 
 import React from 'react';
 import { useUiMode } from '@/components/UiModeProvider';
 
 export default function UiModeControls() {
   const { themeMode, setThemeMode } = useUiMode();
 
   const buttonBase =
     'px-2.5 py-1 rounded border text-xs font-mono transition-colors';
 
   return (
     <div className="flex items-center gap-2">
       <span className="text-[11px] text-foreground/60">Theme</span>
       <div className="flex items-center gap-1">
         <button
           type="button"
           onClick={() => setThemeMode('light')}
           className={`${buttonBase} ${
             themeMode === 'light'
               ? 'border-acidGreen text-acidGreen bg-acidGreen/10'
               : 'border-border/60 text-foreground/70 hover:border-acidGreen/60'
           }`}
         >
           Day
         </button>
         <button
           type="button"
           onClick={() => setThemeMode('dark')}
           className={`${buttonBase} ${
             themeMode === 'dark'
               ? 'border-neonPink text-neonPink bg-neonPink/10'
               : 'border-border/60 text-foreground/70 hover:border-neonPink/60'
           }`}
         >
           Night
         </button>
         <button
           type="button"
           onClick={() => setThemeMode('system')}
           className={`${buttonBase} ${
             themeMode === 'system'
               ? 'border-cyberBlue text-cyberBlue bg-cyberBlue/10'
               : 'border-border/60 text-foreground/70 hover:border-cyberBlue/60'
           }`}
         >
           Auto
         </button>
       </div>
     </div>
   );
 }
