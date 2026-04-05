import { FC } from 'react'
import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import Assets from './pages/Assets'
import AssetDetail from './pages/AssetDetail'
import Alarms from './pages/Alarms'
import OEE from './pages/OEE'

const App: FC = () => {
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<Dashboard />} />
        <Route path="/assets" element={<Assets />} />
        <Route path="/assets/:id" element={<AssetDetail />} />
        <Route path="/alarms" element={<Alarms />} />
        <Route path="/oee" element={<OEE />} />
      </Routes>
    </Layout>
  )
}

export default App
