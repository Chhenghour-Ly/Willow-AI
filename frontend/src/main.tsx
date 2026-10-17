import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, RouterProvider } from 'react-router'
import './styles/tokens.css'
import './styles/site.css'
import './styles/app.css'
import { SiteLayout } from './site/SiteLayout'
import { Home } from './site/Home'
import { About } from './site/About'
import { AppShell } from './app/AppShell'
import { Inbox } from './app/Inbox'
import { Cases } from './app/Cases'
import { CasePage } from './app/CasePage'
import { DetailsPage } from './app/DetailsPage'

const router = createBrowserRouter([
  {
    element: <SiteLayout />,
    children: [
      { path: '/', element: <Home /> },
      { path: '/about', element: <About /> },
    ],
  },
  {
    path: '/app',
    element: <AppShell />,
    children: [
      { index: true, element: <Inbox /> },
      { path: 'cases', element: <Cases /> },
      { path: 'details', element: <DetailsPage /> },
      { path: 'case/:programId', element: <CasePage /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
)
