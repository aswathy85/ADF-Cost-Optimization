from azure.mgmt.datafactory import models as m
copy = m.CopyActivity(name='Heavy_Copy', source=m.DelimitedTextSource(), sink=m.DelimitedTextSink(), inputs=[m.DatasetReference(type='DatasetReference', reference_name='DS_LARGE_SOURCE')], outputs=[m.DatasetReference(type='DatasetReference', reference_name='DS_LARGE_SINK')], parallel_copies={'value':32})
wait = m.WaitActivity(name='Wait_120_Seconds', wait_time_in_seconds={'value':120})
foreach = m.ForEachActivity(name='ForEach_Heavy_Load', items=[1,2,3,4], activities=[copy, wait], is_sequential=False)
pipe = m.PipelineResource(activities=[foreach])
print('Constructed pipeline OK')
print(pipe)
