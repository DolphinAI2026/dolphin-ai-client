import ideFormComponentList from './ide'
import editFormComponentList from './edit'
import readFormComponentList from './read'
import listFormComponentList from './list'
import printFormComponentList from './print'
import searchFormComponentList from './search'
import searchIdeFormComponentList from './search-ide'

const customFormComponentList = [
  ...ideFormComponentList,
  ...editFormComponentList,
  ...readFormComponentList,
  ...listFormComponentList,
  ...printFormComponentList,
  ...searchFormComponentList,
  ...searchIdeFormComponentList
]

export default customFormComponentList
