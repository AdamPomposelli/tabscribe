import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// native desktop shell (Electron): window chrome tweaks
if ((window as unknown as { tabscribe?: { isDesktop?: boolean } }).tabscribe?.isDesktop) document.documentElement.classList.add('desktop')

// no StrictMode: alphaTab owns a worker + audio context that must be created exactly once
createRoot(document.getElementById('root')!).render(<App />)
