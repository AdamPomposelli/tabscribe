import { createRoot } from 'react-dom/client'
import '../index.css'
import './setup.css'
import Setup from './Setup.tsx'

document.documentElement.classList.add('desktop')
createRoot(document.getElementById('root')!).render(<Setup />)
